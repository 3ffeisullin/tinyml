"""Sleep-EDF baseline for the single forehead channel (REQ-ML-01..03).

Compares, under the same leave-subjects-out cross-validation:
  * "device"       - this repo's device feature pipeline (eegml), and
  * "mne_tutorial" - the MNE sleep tutorial's 5 relative band powers,
both on 'EEG Fpz-Cz' only. The MNE tutorial's own result (two EEG channels,
train on one person, test on another) was 68.7 % accuracy, macro F1 0.57.

Run on the PC (downloads ~50 MB per night to ~/mne_data the first time):
    .\\venv\\Scripts\\python.exe scripts\\sleep_edf_baseline.py --subjects 20
Writes reports/sleep_edf_baseline.md and .json.
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
from eegml.sleep_edf import STAGE_NAMES, load_subject, subject_features  # noqa: E402

TUTORIAL = {"accuracy": 0.687, "macro_f1": 0.57}


def collect(subjects, cache: Path):
    cache.mkdir(parents=True, exist_ok=True)
    X1, X2, Y, G = [], [], [], []
    for s in subjects:
        f = cache / f"sc{s:02d}.npz"
        if not f.exists():
            try:
                x, fs, anns = load_subject(s)
            except Exception as e:  # some subject/night combinations are missing upstream
                print(f"  subject {s}: skipped ({e.__class__.__name__}: {e})"); continue
            ours, mne_f, y = subject_features(x, fs, anns)
            np.savez(f, ours=ours, mne=mne_f, y=y)
        d = np.load(f)
        if not len(d["y"]):
            continue
        X1.append(d["ours"]); X2.append(d["mne"]); Y.append(d["y"]); G.append(np.full(len(d["y"]), s))
        print(f"  subject {s}: {len(d['y'])} epochs")
    return np.vstack(X1), np.vstack(X2), np.concatenate(Y), np.concatenate(G)


def evaluate(X, y, groups, folds, seed=241):
    pred = np.empty_like(y)
    for tr, te in GroupKFold(n_splits=folds).split(X, y, groups):
        clf = RandomForestClassifier(n_estimators=100, random_state=seed, n_jobs=-1).fit(X[tr], y[tr])
        pred[te] = clf.predict(X[te])
    labels = list(range(len(STAGE_NAMES)))
    return {
        "accuracy": float(accuracy_score(y, pred)),
        "macro_f1": float(f1_score(y, pred, average="macro", labels=labels, zero_division=0)),
        "recall": dict(zip(STAGE_NAMES, recall_score(y, pred, average=None, labels=labels, zero_division=0).round(3).tolist())),
        "confusion": confusion_matrix(y, pred, labels=labels).tolist(),
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subjects", type=int, default=20, help="first N Sleep-EDF SC subjects (0..82)")
    ap.add_argument("--folds", type=int, default=5)
    ap.add_argument("--cache", type=Path, default=ROOT / "data" / "cache" / "sleep_edf")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    a = ap.parse_args()

    t0 = time.time()
    print(f"Collecting features for subjects 0..{a.subjects - 1}")
    ours, mne_f, y, g = collect(range(a.subjects), a.cache)
    n_subj = len(np.unique(g))
    folds = min(a.folds, n_subj)
    res = {"subjects": n_subj, "epochs": int(len(y)), "folds": folds,
           "class_counts": dict(zip(STAGE_NAMES, np.bincount(y, minlength=5).tolist())),
           "device": evaluate(ours, y, g, folds), "mne_tutorial": evaluate(mne_f, y, g, folds),
           "tutorial_published": TUTORIAL, "seconds": round(time.time() - t0, 1)}

    a.out.mkdir(parents=True, exist_ok=True)
    (a.out / "sleep_edf_baseline.json").write_text(json.dumps(res, indent=2))
    rows = ["| Feature set | Accuracy | Macro F1 | " + " | ".join(f"Recall {s}" for s in STAGE_NAMES) + " |",
            "|---|---|---|" + "---|" * len(STAGE_NAMES)]
    for k, name in [("device", "Device pipeline (eegml)"), ("mne_tutorial", "MNE tutorial features")]:
        r = res[k]
        rows.append(f"| {name} | {r['accuracy']:.3f} | {r['macro_f1']:.3f} | "
                    + " | ".join(f"{r['recall'][s]:.2f}" for s in STAGE_NAMES) + " |")
    md = (f"# Sleep-EDF baseline, Fpz-Cz only\n\n{n_subj} subjects, {len(y)} epochs, "
          f"{folds}-fold leave-subjects-out, random forest (100 trees).\n\n" + "\n".join(rows)
          + f"\n\nPublished MNE tutorial (2 EEG channels, 1 train / 1 test subject): accuracy "
          f"{TUTORIAL['accuracy']}, macro F1 {TUTORIAL['macro_f1']}.\n\nREQ-ML-02 passes if the device "
          f"pipeline's macro F1 >= the MNE-tutorial feature set's under this same split: "
          f"**{'PASS' if res['device']['macro_f1'] >= res['mne_tutorial']['macro_f1'] else 'FAIL'}**\n")
    (a.out / "sleep_edf_baseline.md").write_text(md)
    print(md)


if __name__ == "__main__":
    main()
