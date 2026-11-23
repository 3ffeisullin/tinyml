"""Record a live session from firmware/eeg_node and summarise it (tasks 7a/7, REQ-ACQ-02).

Starts LIVE FAKE, LIVE ADC or LIVE ADC SE on the XIAO, saves every line the board prints
to a log file, stops after --seconds, and prints: samples, measured rate, missed samples,
I2C errors, queue overflows, the fake-path parity result, mean band powers, and any stages.

    .\\venv\\Scripts\\python.exe scripts\\live_log.py --mode fake --seconds 60
    .\\venv\\Scripts\\python.exe scripts\\live_log.py --mode adc --seconds 120 --log data\\bringup_shorted.txt

SAFETY (REQ-SAFE-01..03): with electrodes on a person, the laptop must run on battery
(charger unplugged) or the XIAO must connect through the USB isolator.
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np
import serial

BANDS = ["delta", "theta", "alpha", "sigma", "beta", "gamma"]
MODES = {"fake": "LIVE FAKE", "adc": "LIVE ADC", "adc-se": "LIVE ADC SE"}


def main():
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--mode", choices=MODES, default="fake")
    ap.add_argument("--seconds", type=float, default=60)
    ap.add_argument("--port", default="COM5")
    ap.add_argument("--log", type=Path, default=None, help="where to save the raw lines (default: none)")
    a = ap.parse_args()

    lines = []
    with serial.Serial(a.port, 115200, timeout=0.5) as p:
        p.dtr = False; p.rts = True; time.sleep(0.1); p.rts = False  # reset: fresh session
        p.close(); time.sleep(1.5); p.open()
        end = time.time() + 30
        while time.time() < end:
            line = p.readline().decode(errors="replace").strip()
            if line:
                lines.append(line)
            if line == "READY":
                break
        else:
            sys.exit("Error: the board did not print READY")
        adc_line = next((l for l in lines if l.startswith("ADC ")), "ADC ?")
        print(adc_line)
        p.write((MODES[a.mode] + "\n").encode())
        t0 = time.time()
        while time.time() - t0 < a.seconds:
            line = p.readline().decode(errors="replace").strip()
            if not line:
                continue
            lines.append(line)
            if line.startswith(("OK", "ERR", "FAKE", "STAT", "EPOCH", "OUT")):
                print(" ", line, flush=True)
            if line.startswith("ERR"):
                break
        p.write(b"STAT\nSTOP\n")
        end = time.time() + 3
        while time.time() < end:
            line = p.readline().decode(errors="replace").strip()
            if line:
                lines.append(line)

    if a.log:
        a.log.parent.mkdir(parents=True, exist_ok=True)
        a.log.write_text("\n".join(lines) + "\n", encoding="utf-8")
        print(f"saved {len(lines)} lines to {a.log}")
    w = np.array([[float(v) for v in l.split()[1:]] for l in lines if l.startswith("W ")])
    stat = [l for l in lines if l.startswith("STAT")]
    print("\nSummary")
    if stat:
        print(" ", stat[-1])
    if len(w):
        print(f"  {len(w)} one-second windows; mean log10 band power (uV^2): "
              + ", ".join(f"{b} {m:.2f}" for b, m in zip(BANDS, w[:, 1:7].mean(0))))
        print(f"  mean relative alpha {w[:, 7].mean():.3f}, peak-to-peak median {np.median(w[:, 8]):.1f} uV, "
              f"mains ratio median {np.median(w[:, 9]):.3f}, clip fraction max {w[:, 10].max():.3f}")
    for l in lines:
        if l.startswith("FAKE PARITY"):
            print(" ", l)
    stages = [l.split()[2] for l in lines if l.startswith("OUT")]
    if stages:
        print(f"  stages: {' '.join(stages)}")


if __name__ == "__main__":
    main()
