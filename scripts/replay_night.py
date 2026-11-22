"""Replay a Sleep-EDF night through the XIAO and compare it with Python, epoch by epoch (task 6b).

The laptop plays the sensor: it sends the night's Fpz-Cz signal, resampled to 250 Hz
(what the headband records), to firmware/eeg_node one 30 s epoch at a time. The board
runs the whole chain on its own: filters -> window features -> epoch summaries ->
running standardisation -> [t, t-1, t-2] -> int8 model -> stage. Python runs the same
chain on the same float32 samples (eegml.sleep_edf.device_epoch_features,
eegml.sleep_model.model_input, the int8 model from sleep_model.h).

Reported:
  * parity: epoch features (max relative error), int8 model outputs (exact match), stages;
  * accuracy of the board's stages against the hypnogram (the default subject, 20, is not
    in the model's 20 training subjects 0-19, so this is a held-out night);
  * board time per epoch.

    .\\venv\\Scripts\\python.exe scripts\\replay_night.py --subject 20 --port COM5
Downloads the night once (~50 MB, MNE cache). Writes reports/replay_scNN.md, .json and
a per-epoch .csv. No electrodes or sensor needed; the XIAO only needs USB.
"""
import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np
import serial
from sklearn.metrics import accuracy_score, confusion_matrix, f1_score, recall_score

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from eegml import sleep_model as sm  # noqa: E402
from eegml.config import EPOCH_S, FS  # noqa: E402
from eegml.epochs import EPOCH_FEATURE_NAMES  # noqa: E402
from eegml.sleep_edf import STAGE_NAMES, device_epoch_features, device_segment, load_subject  # noqa: E402

EPOCH_N = int(round(EPOCH_S * FS))
HEADER = ROOT / "firmware" / "eeg_node" / "sleep_model.h"
LINE_FREQ = 50.0  # Sleep-EDF was recorded with 50 Hz mains
CHUNK = 4096      # bytes per write; must match kChunk in eeg_node.ino


def python_reference(seg32: np.ndarray, n_epochs: int):
    """Epoch features, int8 model inputs/outputs and stages, as the board should produce them."""
    offsets = np.arange(n_epochs) * EPOCH_N
    feats = device_epoch_features(seg32.astype(np.float64), offsets, LINE_FREQ)
    if np.isnan(feats).any():
        sys.exit("Error: an epoch has no full window; pick another subject.")
    text = HEADER.read_text()
    runner = sm.Int8Runner(bytes(sm.parse_header_array(text, "g_sleep_model").astype(np.uint8)))
    xq = runner.quantise(sm.model_input(feats))
    out = runner.predict_q(xq)
    return feats, out, out.argmax(1)


def read_until(port, prefix: str, timeout: float, sink: list):
    """Read lines until one starts with prefix; keep every line in sink."""
    end = time.time() + timeout
    while time.time() < end:
        line = port.readline().decode(errors="replace").strip()
        if not line:
            continue
        sink.append(line)
        if line.startswith("ERR"):
            raise RuntimeError(line)
        if line.startswith(prefix):
            return line
    raise TimeoutError(f"no '{prefix}' from the board within {timeout:.0f} s")


def run_board(port_name: str, seg32: np.ndarray, n_epochs: int, log: list):
    feats = np.full((n_epochs, len(EPOCH_FEATURE_NAMES)), np.nan)
    windows = np.zeros(n_epochs, int)
    out = np.full((n_epochs, 5), -999, int)
    stage_names = {}
    us = np.zeros(n_epochs)
    with serial.Serial(port_name, 115200, timeout=1) as p:
        p.dtr = False; p.rts = True; time.sleep(0.1); p.rts = False  # reset: fresh self-tests
        p.close(); time.sleep(1.5); p.open()
        read_until(p, "READY", 30, log)
        p.write(f"BEGIN {LINE_FREQ:g}\n".encode())
        read_until(p, "OK BEGIN", 5, log)
        t0 = time.time()
        for e in range(n_epochs):
            data = seg32[e * EPOCH_N:(e + 1) * EPOCH_N].astype("<f4").tobytes()
            p.write(b"EPOCH\n")
            for i in range(0, len(data), CHUNK):  # flow control: the board answers "C" per chunk
                p.write(data[i:i + CHUNK])
                read_until(p, "C", 10, [])
            lines = []
            ack = read_until(p, "ACK", 30, lines)
            log.extend(lines)
            us[e] = float(ack.split()[2])
            for line in lines:
                parse_line(line, feats, windows, out, stage_names)
            if e % 100 == 0 or e == n_epochs - 1:
                print(f"  epoch {e + 1}/{n_epochs}  {time.time() - t0:.0f} s", flush=True)
        p.write(b"END\n")
        lines = []
        read_until(p, "DONE", 10, lines)
        log.extend(lines)
        for line in lines:
            parse_line(line, feats, windows, out, stage_names)
    return feats, windows, out, us


def parse_line(line, feats, windows, out, stage_names):
    parts = line.split()
    if parts[0] == "FEAT":
        e = int(parts[1]); windows[e] = int(parts[2]); feats[e] = [float(v) for v in parts[3:]]
    elif parts[0] == "OUT":
        t = int(parts[1]); stage_names[t] = parts[2]; out[t] = [int(v) for v in parts[3:8]]


def scores(y, pred):
    labels = list(range(len(STAGE_NAMES)))
    return {"accuracy": float(accuracy_score(y, pred)),
            "macro_f1": float(f1_score(y, pred, average="macro", labels=labels, zero_division=0)),
            "recall": dict(zip(STAGE_NAMES, recall_score(y, pred, average=None, labels=labels,
                                                         zero_division=0).round(3).tolist())),
            "confusion": confusion_matrix(y, pred, labels=labels).tolist()}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--subject", type=int, default=20, help="Sleep-EDF SC subject (training used 0-19)")
    ap.add_argument("--port", default="COM5")
    ap.add_argument("--max-epochs", type=int, default=0, help="0 = whole night")
    ap.add_argument("--out", type=Path, default=ROOT / "reports")
    a = ap.parse_args()

    x, fs, anns = load_subject(a.subject)
    seg, offsets, y_scored, _ = device_segment(x, fs, anns)
    if np.any(offsets % EPOCH_N):
        sys.exit("Error: scored epochs are not on 30 s boundaries of the segment.")
    # The device sees a continuous signal: every 30 s slot is an epoch. Slots the hypnogram
    # doesn't stage (movement time, '?') are processed but not scored (label -1).
    n_slots = len(seg) // EPOCH_N
    labels = np.full(n_slots, -1)
    labels[offsets // EPOCH_N] = y_scored
    n = n_slots if a.max_epochs <= 0 else min(a.max_epochs, n_slots)
    seg32, labels = seg[:n * EPOCH_N].astype(np.float32), labels[:n]
    print(f"Subject {a.subject}: {n} epochs ({n * EPOCH_S / 3600:.1f} h), {int((labels < 0).sum())} unscored, "
          f"{n * EPOCH_N * 4 / 1e6:.1f} MB to send", flush=True)

    ref_feats, ref_out, ref_stage = python_reference(seg32, n)
    log = []
    t0 = time.time()
    dev_feats, windows, dev_out, us = run_board(a.port, seg32, n, log)
    wall = time.time() - t0
    dev_stage = dev_out.argmax(1)
    scored = labels >= 0
    y = labels[scored]

    rel = np.abs(dev_feats - ref_feats) / (np.abs(ref_feats) + 1e-6)
    res = {
        "subject": a.subject, "epochs": int(n), "scored_epochs": int(scored.sum()),
        "hours": round(n * EPOCH_S / 3600, 2),
        "in_training_set": a.subject < 20,
        "parity": {
            "windows_per_epoch": sorted(set(windows.tolist())),
            "feature_max_rel_error": float(np.nanmax(rel)),
            "feature_p99_rel_error": float(np.nanpercentile(rel, 99)),
            "feature_worst": EPOCH_FEATURE_NAMES[int(np.nanargmax(np.nanmax(rel, 0)))],
            "int8_outputs_identical": float((dev_out == ref_out).all(1).mean()),
            "int8_max_abs_diff": int(np.abs(dev_out - ref_out).max()),
            "stage_agreement": float((dev_stage == ref_stage).mean()),
            "stage_disagreements": int((dev_stage != ref_stage).sum()),
        },
        "board_vs_hypnogram": scores(y, dev_stage[scored]),
        "python_vs_hypnogram": scores(y, ref_stage[scored]),
        "class_counts": dict(zip(STAGE_NAMES, np.bincount(y, minlength=5).tolist())),
        "board_us_per_epoch": {"median": float(np.median(us)), "max": float(us.max())},
        "wall_seconds": round(wall, 1),
    }
    a.out.mkdir(parents=True, exist_ok=True)
    stem = f"replay_sc{a.subject:02d}"
    (a.out / f"{stem}.json").write_text(json.dumps(res, indent=2))
    with open(a.out / f"{stem}.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["epoch", "hypnogram", "python_stage", "board_stage", "board_scores_int8"])
        for e in range(n):
            w.writerow([e, STAGE_NAMES[labels[e]] if labels[e] >= 0 else "unscored",
                        STAGE_NAMES[ref_stage[e]], STAGE_NAMES[dev_stage[e]],
                        " ".join(map(str, dev_out[e]))])
    md = report(res)
    (a.out / f"{stem}.md").write_text(md, encoding="utf-8")
    print(md)


def report(r):
    pa, b, py = r["parity"], r["board_vs_hypnogram"], r["python_vs_hypnogram"]
    conf = ["| true \\ board | " + " | ".join(STAGE_NAMES) + " |", "|---|" + "---|" * 5]
    conf += [f"| {s} | " + " | ".join(map(str, row)) + " |" for s, row in zip(STAGE_NAMES, b["confusion"])]
    held = "not in the model's training subjects (0–19): a held-out night" if not r["in_training_set"] \
        else "one of the model's training subjects, so accuracy is optimistic"
    return f"""# Replay of Sleep-EDF subject {r['subject']} through the XIAO (task 6b)

{r['epochs']} epochs ({r['hours']} h; {r['scored_epochs']} with a hypnogram stage, the rest are movement
time or unscored and are processed but not scored), subject {r['subject']} is {held}. The laptop streamed the Fpz-Cz
signal, resampled to 250 Hz, as float32; the board ran filters (50 Hz chain), window features, epoch
summaries, running standardisation, the 3-epoch stack and the int8 model. Python ran the same chain on
the same samples. Generated by `scripts/replay_night.py`.

## Board vs Python (parity)

| Check | Result |
|---|---|
| Windows per epoch | {pa['windows_per_epoch']} |
| Epoch features, max relative error | {pa['feature_max_rel_error']:.2g} (99th percentile {pa['feature_p99_rel_error']:.2g}; worst: {pa['feature_worst']}) |
| Int8 model outputs identical | {pa['int8_outputs_identical']:.2%} of epochs (max difference {pa['int8_max_abs_diff']} LSB) |
| Stage agreement | {pa['stage_agreement']:.2%} ({pa['stage_disagreements']} epochs differ) |
| Board time per epoch (30 s of signal) | median {r['board_us_per_epoch']['median'] / 1000:.0f} ms, max {r['board_us_per_epoch']['max'] / 1000:.0f} ms |

## Board vs the hypnogram (one night)

| | Accuracy | Macro F1 | {" | ".join(f"Recall {s}" for s in STAGE_NAMES)} |
|---|---|---|{"---|" * 5}
| Board | {b['accuracy']:.3f} | {b['macro_f1']:.3f} | {" | ".join(f"{b['recall'][s]:.2f}" for s in STAGE_NAMES)} |
| Python | {py['accuracy']:.3f} | {py['macro_f1']:.3f} | {" | ".join(f"{py['recall'][s]:.2f}" for s in STAGE_NAMES)} |

Class counts: {", ".join(f"{k} {v}" for k, v in r['class_counts'].items())}. One night is a small sample; the
cross-validated figures are in `reports/sleep_model.md`.

{chr(10).join(conf)}
"""


if __name__ == "__main__":
    main()
