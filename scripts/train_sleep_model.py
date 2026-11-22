"""Int8 sleep-stage model on the cached Sleep-EDF features (REQ-ML-03/04, REQ-FEAT-10).

Reads data/cache/sleep_edf/scNN.npz written by scripts/sleep_edf_baseline.py
(never downloads). Per subject: standardise the 30 device features with a
running mean/SD as the device will (REQ-FEAT-10; --standardise whole-night for
the offline reference), clip, and append the previous 2 epochs
(eegml.sleep_model.model_input).

Evaluation uses the baseline's split exactly: GroupKFold(5) over subjects on the
same epoch order. Per fold it trains the float net (early stopping on 3 training
subjects held out for validation), quantises it to int8 with a representative
set drawn from that fold's training subjects only, and scores float, int8 and the
baseline random forest (raw features, 100 trees, seed 241) plus a random forest
on the net's own inputs. Then it trains one final model on all subjects and
exports it to firmware/eeg_node/sleep_model.h.

    .\\venv\\Scripts\\python.exe scripts\\train_sleep_model.py
Writes reports/sleep_model.md and .json.
"""
import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score
from sklearn.model_selection import GroupKFold

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eegml import sleep_model as sm  # noqa: E402
from eegml.sleep_edf import STAGE_NAMES  # noqa: E402

SEED = 241
N_VAL_SUBJECTS = 3
REP_SIZE = 1000
FLASH_LIMIT, ARENA_LIMIT = 64 * 1024, 32 * 1024  # REQ-ML-04


def load_cache(cache: Path, n_subjects: int, mode: str = sm.STANDARDISE):
    raw, inp, y, g = [], [], [], []
    for s in range(n_subjects):
        f = cache / f"sc{s:02d}.npz"
        if not f.exists():
            sys.exit(f"Error: {f} missing. Run scripts/sleep_edf_baseline.py first (this script never downloads).")
        d = np.load(f)
        if not len(d["y"]):
            continue
        raw.append(d["ours"]); inp.append(sm.model_input(d["ours"], mode=mode)); y.append(d["y"])
        g.append(np.full(len(d["y"]), s))
    return np.vstack(raw), np.vstack(inp), np.concatenate(y), np.concatenate(g)


def class_weights(y):
    """Inverse-sqrt frequency, mean 1: lifts N1 without wrecking N2."""
    c = np.bincount(y, minlength=len(STAGE_NAMES)).astype(float)
    w = 1 / np.sqrt(np.maximum(c, 1))
    w *= len(c) / w.sum()
    return {i: float(v) for i, v in enumerate(w)}


def fit_float(x, y, groups, rng, max_epochs, fixed_epochs=None):
    """Train the net. With fixed_epochs=None, early-stop on N_VAL_SUBJECTS held-out subjects."""
    import tensorflow as tf
    tf.keras.utils.set_random_seed(int(rng.integers(1 << 30)))
    model = sm.build_model()
    kw = dict(batch_size=128, verbose=0, class_weight=class_weights(y))
    if fixed_epochs is not None:
        model.fit(x, y, epochs=fixed_epochs, **kw)
        return model, fixed_epochs
    val_subj = rng.choice(np.unique(groups), N_VAL_SUBJECTS, replace=False)
    v = np.isin(groups, val_subj)
    es = tf.keras.callbacks.EarlyStopping(monitor="val_loss", patience=10, restore_best_weights=True)
    h = model.fit(x[~v], y[~v], validation_data=(x[v], y[v]), epochs=max_epochs, callbacks=[es], **kw)
    return model, int(np.argmin(h.history["val_loss"]) + 1)


def metrics(y, pred):
    labels = list(range(len(STAGE_NAMES)))
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", labels=labels, zero_division=0)),
        "recall": dict(zip(STAGE_NAMES, recall_score(y, pred, average=None, labels=labels, zero_division=0).round(3).tolist())),
        "confusion": confusion_matrix(y, pred, labels=labels).tolist(),
    }


def arena_estimate(tflite: bytes):
    """Rough TFLM arena need: all non-constant tensors + per-tensor/op bookkeeping, 1 KB margin.

    TFLM plans activations into shared memory, so summing them over-counts; the
    per-tensor (64 B) and per-op (256 B) allowances cover TfLiteEvalTensor and
    node data. Measure the real value on the device (task 4b).
    """
    import tensorflow as tf
    it = tf.lite.Interpreter(model_content=tflite)
    it.allocate_tensors()
    det = it.get_tensor_details()
    const = set()
    for op in it._get_ops_details():  # inputs that are weights/biases
        const.update(i for i in op["inputs"][1:] if i >= 0)
    act = sum(int(np.prod(d["shape"])) * np.dtype(d["dtype"]).itemsize for d in det if d["index"] not in const)
    est = act + 64 * len(det) + 256 * len(it._get_ops_details()) + 1024
    return {"activation_bytes": act, "tensors": len(det), "ops": len(it._get_ops_details()),
            "estimate_bytes": int(est), "recommended_arena_bytes": int(max(4096, -(-2 * est // 1024) * 1024))}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subjects", type=int, default=20)
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--max-epochs", type=int, default=150)
    ap.add_argument("--standardise", choices=["running", "whole-night"], default=sm.STANDARDISE,
                    help="per-subject standardisation (running = device behaviour, REQ-FEAT-10)")
    ap.add_argument("--cache", type=Path, default=ROOT / "data" / "cache" / "sleep_edf")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    ap.add_argument("--header", type=Path, default=ROOT / "firmware" / "eeg_node" / "sleep_model.h")
    a = ap.parse_args()

    t0 = time.time()
    rng = np.random.default_rng(SEED)
    raw, x, y, g = load_cache(a.cache, a.subjects, a.standardise)
    folds = min(a.folds, len(np.unique(g)))
    print(f"{len(np.unique(g))} subjects, {len(y)} epochs, input {x.shape[1]}", flush=True)

    p = {k: np.empty_like(y) for k in ("float", "int8", "rf_baseline", "rf_same_input")}
    fold_info = []
    for k, (tr, te) in enumerate(GroupKFold(n_splits=folds).split(raw, y, g)):
        model, best = fit_float(x[tr], y[tr], g[tr], rng, a.max_epochs)
        p["float"][te] = model.predict(x[te], verbose=0).argmax(1)
        rep = x[tr][rng.choice(len(tr), min(REP_SIZE, len(tr)), replace=False)]
        p["int8"][te] = sm.Int8Runner(sm.to_int8(model, rep)).predict(x[te])
        rf = dict(n_estimators=100, random_state=SEED, n_jobs=-1)
        p["rf_baseline"][te] = RandomForestClassifier(**rf).fit(raw[tr], y[tr]).predict(raw[te])
        p["rf_same_input"][te] = RandomForestClassifier(**rf).fit(x[tr], y[tr]).predict(x[te])
        agree = float((p["float"][te] == p["int8"][te]).mean())
        fold_info.append({"fold": k, "test_subjects": sorted(np.unique(g[te]).tolist()), "best_epoch": best,
                          "float_acc": float((p["float"][te] == y[te]).mean()), "agreement": agree})
        print(f"  fold {k}: subjects {fold_info[-1]['test_subjects']} best epoch {best} "
              f"float acc {fold_info[-1]['float_acc']:.3f} int8 agreement {agree:.4f}", flush=True)

    # Final deployable model: all subjects, epoch count = median of the folds' best epochs.
    n_ep = int(np.median([f["best_epoch"] for f in fold_info]))
    final, _ = fit_float(x, y, g, rng, a.max_epochs, fixed_epochs=n_ep)
    tflite = sm.to_int8(final, x[rng.choice(len(x), REP_SIZE, replace=False)])
    runner = sm.Int8Runner(tflite)
    final_agree = float((final.predict(x, verbose=0).argmax(1) == runner.predict(x)).mean())
    arena = arena_estimate(tflite)

    # One test epoch per stage from subject 0 for the on-device parity check (task 4b).
    samples = {}
    for c, name in enumerate(STAGE_NAMES):
        i = int(np.flatnonzero((g == g.min()) & (y == c))[0])
        xq = runner.quantise(x[i:i + 1])
        samples[name.lower()] = (xq[0], runner.predict_q(xq)[0], c)
    a.header.parent.mkdir(parents=True, exist_ok=True)
    a.header.write_text(sm.header_text(tflite, runner, samples, STAGE_NAMES, arena["recommended_arena_bytes"]))

    res = {"subjects": int(len(np.unique(g))), "epochs": int(len(y)), "folds": folds,
           "input": {"features": sm.N_FEATURES, "neighbours": sm.NEIGHBOURS, "size": sm.N_INPUT,
                     "clip": sm.INPUT_CLIP, "standardisation": a.standardise, "warmup_epochs": sm.WARMUP},
           "model": {"layers": "Dense(32,relu)-Dropout-Dense(16,relu)-Dropout-Dense(5,softmax)",
                     "params": int(final.count_params()), "class_weight": "inverse sqrt frequency"},
           "cv": {k: metrics(y, v) for k, v in p.items()},
           "agreement_cv": float((p["float"] == p["int8"]).mean()),
           "folds_detail": fold_info,
           "final": {"train_epochs": n_ep, "agreement_train": final_agree, "tflite_bytes": len(tflite),
                     "arena": arena,
                     "header": str(a.header.resolve().relative_to(ROOT) if a.header.resolve().is_relative_to(ROOT)
                                   else a.header).replace("\\", "/")},
           "seconds": round(time.time() - t0, 1)}
    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "sleep_model.json").write_text(json.dumps(res, indent=2))
    # Out-of-fold stages per epoch (each night staged by a model that never saw that person), for
    # per-night reports such as scripts/stage_minutes_report.py. Epochs are in recording order per subject.
    np.savez_compressed(a.out / "sleep_model_cv_predictions.npz", y=y, subject=g, stages=np.array(STAGE_NAMES),
                        **{k: v.astype(np.int8) for k, v in p.items()})
    md = report_md(res)
    (a.out / "sleep_model.md").write_text(md, encoding="utf-8")
    print(md)


def report_md(r):
    cv = r["cv"]
    names = [("float", "Dense net, float"), ("int8", "Dense net, int8"),
             ("rf_baseline", "Random forest, baseline (raw features)"),
             ("rf_same_input", "Random forest, same input as the net")]
    rows = ["| Model | Accuracy | Macro F1 | " + " | ".join(f"Recall {s}" for s in STAGE_NAMES) + " |",
            "|---|---|---|" + "---|" * len(STAGE_NAMES)]
    for k, n in names:
        m = cv[k]
        rows.append(f"| {n} | {m['accuracy']:.3f} | {m['macro_f1']:.3f} | "
                    + " | ".join(f"{m['recall'][s]:.2f}" for s in STAGE_NAMES) + " |")
    conf = ["| true \\ pred | " + " | ".join(STAGE_NAMES) + " |", "|---|" + "---|" * len(STAGE_NAMES)]
    for s, row in zip(STAGE_NAMES, cv["int8"]["confusion"]):
        conf.append(f"| {s} | " + " | ".join(str(v) for v in row) + " |")
    f, ar = r["final"], r["final"]["arena"]
    beats = cv["int8"]["macro_f1"] > cv["rf_baseline"]["macro_f1"]
    ag_ok = r["agreement_cv"] >= 0.98
    fits = f["tflite_bytes"] <= FLASH_LIMIT and ar["recommended_arena_bytes"] <= ARENA_LIMIT
    folds = "\n".join(f"| {d['fold']} | {', '.join(map(str, d['test_subjects']))} | {d['best_epoch']} | "
                      f"{d['float_acc']:.3f} | {d['agreement']:.4f} |" for d in r["folds_detail"])
    std_text = (f"a running mean/SD as on the device (REQ-FEAT-10): the first {r['input']['warmup_epochs']} epochs "
                "use their own stats, later epochs the stats of all epochs so far"
                if r["input"]["standardisation"] == "running" else
                "the whole night's mean/SD (offline reference; the device cannot do this, see "
                "`reports/calibration_ablation.md`)")
    return f"""# Int8 sleep-stage model, Fpz-Cz only

{r['subjects']} subjects, {r['epochs']} epochs, {r['folds']}-fold leave-subjects-out (GroupKFold, the
same split as `reports/sleep_edf_baseline.md`). Generated by `scripts/train_sleep_model.py`.

**Input** ({r['input']['size']} values): the {r['input']['features']} device epoch features, z-scored
per subject with {std_text}, clipped to ±{r['input']['clip']:g}, for the current epoch and the previous
{r['input']['neighbours']}.
**Model:** {r['model']['layers']}, {r['model']['params']} parameters, class weights
{r['model']['class_weight']}. Int8: full-integer post-training quantisation, representative set
from each fold's training subjects only.

## Cross-validated results (held-out subjects)

{chr(10).join(rows)}

Float/int8 agreement on held-out epochs: **{r['agreement_cv']:.2%}** (REQ-ML-03 needs ≥ 98 %:
**{'PASS' if ag_ok else 'FAIL'}**).

Int8 model vs baseline random forest, macro F1: {cv['int8']['macro_f1']:.3f} vs
{cv['rf_baseline']['macro_f1']:.3f} → **{'beats' if beats else 'does not beat'} the random forest**
(accuracy {cv['int8']['accuracy']:.3f} vs {cv['rf_baseline']['accuracy']:.3f}). A random forest given the
net's own input reaches macro F1 {cv['rf_same_input']['macro_f1']:.3f}; per-subject standardisation and the
previous-epoch context account for much of the gain, and the net is the model small enough for the XIAO.

### Int8 confusion matrix

{chr(10).join(conf)}

### Per fold

| Fold | Test subjects | Best epoch | Float accuracy | Float/int8 agreement |
|---|---|---|---|---|
{folds}

## Deployed model (`{f['header']}`)

Trained on all {r['subjects']} subjects for {f['train_epochs']} epochs (median of the folds' early-stopping
points); float/int8 agreement on its training data {f['agreement_train']:.2%}.

| Item | Value | REQ-ML-04 limit |
|---|---|---|
| `.tflite` size | {f['tflite_bytes']:,} bytes | 65,536 bytes flash |
| Activations (sum of non-constant tensors) | {ar['activation_bytes']:,} bytes | — |
| Arena estimate ({ar['tensors']} tensors, {ar['ops']} ops, with bookkeeping) | {ar['estimate_bytes']:,} bytes | — |
| Arena to allocate (2× estimate, ≥ 4 KB) | {ar['recommended_arena_bytes']:,} bytes | 32,768 bytes |

Size and arena fit the limits on paper: **{'yes' if fits else 'no'}**. REQ-ML-04 also needs the
device measurement (arena used, µs per inference), which is task 4b.

The header also carries the input/output quantisation, the feature order, the clip value, and one
int8 test input per stage with the expected int8 output, for the on-device parity check.

## Caveats

- Standardisation uses each night's full mean/SD; the device will use ~60 s of calibration, which is
  noisier. Expect some loss on the device until this is simulated (e.g. stats from the first minutes).
- The previous-epoch stack assumes consecutive epochs; the cache keeps no onsets, so the few epochs
  dropped for missing windows (none in subject 0) join their neighbours across a gap.
"""


if __name__ == "__main__":
    main()
