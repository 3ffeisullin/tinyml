"""Per-night minutes per sleep stage: model vs sleep experts.

Overall accuracy can look fine while a night's sleep measures are wrong: on held-out night
SC20 the board gives 45 min of deep sleep (N3) against the experts' 2 min. This report
judges each measure a user would read, night by night:

  * minutes in W, N1, N2, N3 and REM;
  * total sleep time (N1 + N2 + N3 + REM) and deep sleep as a share of it.

Sources:
  * reports/sleep_model_cv_predictions.npz: out-of-fold stages from scripts/train_sleep_model.py
    (each of the 20 nights staged by a model that never saw that person). "int8" is the
    deployed model type; "rf_baseline" is the random-forest baseline for comparison.
  * reports/replay_sc20.csv: the held-out night SC20 staged on the XIAO itself (task 6b).

Minutes are counted over scored epochs inside the analysed window (30 min of wake kept before
the first and after the last sleep; movement and '?' epochs excluded), so W minutes are not
time in bed.

    .\\venv\\Scripts\\python.exe scripts\\stage_minutes_report.py
Writes reports/stage_minutes.md, .json and a per-night .csv.
"""
import csv
import json
import sys
from pathlib import Path

import numpy as np
from sklearn.metrics import f1_score

ROOT = Path(__file__).resolve().parents[1]
STAGES = ["W", "N1", "N2", "N3", "REM"]
SLEEP = [1, 2, 3, 4]
EPOCH_MIN = 0.5
MEASURES = STAGES + ["TST", "N3_pct"]
LABELS = {"W": "Wake", "N1": "N1 (light)", "N2": "N2", "N3": "N3 (deep)", "REM": "REM",
          "TST": "Total sleep time", "N3_pct": "Deep sleep, % of total sleep"}


def night_measures(stages: np.ndarray) -> dict:
    """Minutes per stage, total sleep time (min) and N3 as % of total sleep, for one night."""
    c = np.bincount(np.asarray(stages, int), minlength=len(STAGES))
    m = {s: float(c[i] * EPOCH_MIN) for i, s in enumerate(STAGES)}
    m["TST"] = float(c[SLEEP].sum() * EPOCH_MIN)
    m["N3_pct"] = float(100 * c[3] / c[SLEEP].sum()) if c[SLEEP].sum() else 0.0
    return m


def compare_night(y: np.ndarray, pred: np.ndarray) -> dict:
    t, p = night_measures(y), night_measures(pred)
    return {"experts": t, "model": p, "error": {k: p[k] - t[k] for k in MEASURES},
            "accuracy": float((y == pred).mean()),
            "macro_f1": float(f1_score(y, pred, average="macro", labels=list(range(5)), zero_division=0))}


def summarise(nights: dict) -> dict:
    """Across nights, per measure: mean experts / model, bias (mean error), mean absolute error,
    worst night and the correlation between experts' and model values."""
    out = {}
    for k in MEASURES:
        t = np.array([n["experts"][k] for n in nights.values()])
        p = np.array([n["model"][k] for n in nights.values()])
        e = p - t
        worst = list(nights)[int(np.argmax(np.abs(e)))]
        r = float(np.corrcoef(t, p)[0, 1]) if len(t) > 2 and t.std() > 0 and p.std() > 0 else float("nan")
        out[k] = {"experts_mean": float(t.mean()), "model_mean": float(p.mean()), "bias": float(e.mean()),
                  "mae": float(np.abs(e).mean()), "worst_night": worst, "worst_error": float(e[list(nights).index(worst)]),
                  "r": r}
    return out


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    d = np.load(ROOT / "reports" / "sleep_model_cv_predictions.npz")
    y, subj = d["y"], d["subject"]
    res = {"nights": {}, "summary": {}}
    for model in ("int8", "rf_baseline"):
        nights = {f"SC{s:02d}": compare_night(y[subj == s], d[model][subj == s].astype(int)) for s in np.unique(subj)}
        res["nights"][model] = nights
        res["summary"][model] = summarise(nights)

    with open(ROOT / "reports" / "replay_sc20.csv", newline="") as fh:
        rows = [r for r in csv.DictReader(fh) if r["hypnogram"] != "unscored"]
    res["board_sc20"] = compare_night(np.array([STAGES.index(r["hypnogram"]) for r in rows]),
                                      np.array([STAGES.index(r["board_stage"]) for r in rows]))

    out = ROOT / "reports"
    (out / "stage_minutes.json").write_text(json.dumps(res, indent=2))
    with open(out / "stage_minutes.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["night", "source"] + [f"{k}_{who}" for k in MEASURES for who in ("experts", "model")]
                   + ["accuracy", "macro_f1"])
        for model, nights in res["nights"].items():
            for name, n in nights.items():
                w.writerow([name, f"cv_{model}"] + [round(n[who][k], 2) for k in MEASURES for who in ("experts", "model")]
                           + [round(n["accuracy"], 4), round(n["macro_f1"], 4)])
        n = res["board_sc20"]
        w.writerow(["SC20", "board_replay"] + [round(n[who][k], 2) for k in MEASURES for who in ("experts", "model")]
                   + [round(n["accuracy"], 4), round(n["macro_f1"], 4)])
    md = report_md(res)
    (out / "stage_minutes.md").write_text(md, encoding="utf-8")
    print(md)


def fmt(k, v, signed=False):
    unit = " %" if k == "N3_pct" else ""
    return f"{v:+.1f}{unit}" if signed else f"{v:.1f}{unit}"


def report_md(r):
    s, nights = r["summary"]["int8"], r["nights"]["int8"]
    rf = r["summary"]["rf_baseline"]
    L = ["# Minutes per sleep stage, per night: model vs sleep experts", "",
         "Each of the 20 Sleep-EDF nights staged by a model that never saw that person (5-fold, split by person); "
         "int8 model as deployed. Minutes are over scored epochs in the analysed window (wake trimmed to 30 min "
         "before and after sleep), so wake minutes are not time in bed. Bias = mean (model − experts); "
         "MAE = mean absolute error; r = correlation across nights. Generated by `scripts/stage_minutes_report.py`.", "",
         "## Across 20 nights (int8 model)", "",
         "| Measure | Experts, mean | Model, mean | Bias | MAE | Worst night (error) | r | MAE, random-forest baseline |",
         "|---|---|---|---|---|---|---|---|"]
    for k in MEASURES:
        v = s[k]
        L.append(f"| {LABELS[k]}{'' if k == 'N3_pct' else ' (min)'} | {fmt(k, v['experts_mean'])} | "
                 f"{fmt(k, v['model_mean'])} | {fmt(k, v['bias'], True)} | {fmt(k, v['mae'])} | "
                 f"{v['worst_night']} ({fmt(k, v['worst_error'], True)}) | {v['r']:.2f} | {fmt(k, rf[k]['mae'])} |")
    L += ["", "## Deep sleep (N3) per night", "",
          "| Night | Experts (min) | Model (min) | Error (min) | Experts, % of sleep | Model, % of sleep | Macro F1 |",
          "|---|---|---|---|---|---|---|"]
    for name, n in sorted(nights.items(), key=lambda kv: -abs(kv[1]["error"]["N3"])):
        L.append(f"| {name} | {n['experts']['N3']:.1f} | {n['model']['N3']:.1f} | {n['error']['N3']:+.1f} | "
                 f"{n['experts']['N3_pct']:.1f} | {n['model']['N3_pct']:.1f} | {n['macro_f1']:.3f} |")
    b = r["board_sc20"]
    L += ["", "## Held-out night SC20, staged on the XIAO (task 6b replay)", "",
          "Subject 20 was not in training; the board's stages equal the PC's on every epoch.", "",
          "| Measure | Experts | Board | Error |", "|---|---|---|---|"]
    for k in MEASURES:
        L.append(f"| {LABELS[k]}{'' if k == 'N3_pct' else ' (min)'} | {fmt(k, b['experts'][k])} | "
                 f"{fmt(k, b['model'][k])} | {fmt(k, b['error'][k], True)} |")
    L += ["", f"Accuracy {b['accuracy']:.3f}, macro F1 {b['macro_f1']:.3f}.", ""]
    return "\n".join(L)


if __name__ == "__main__":
    main()
