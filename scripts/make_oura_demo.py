"""Build the Oura demo nights (tests/fixtures/oura_demo/) from cached Sleep-EDF hypnograms.

Sleep stages are the Sleep-EDF experts' (one night per subject, subjects 0..N-1); heart rate, HRV and
scores are simulated (hub/oura_app/demo_data.py). No personal Oura data is read or written.

    .\\venv\\Scripts\\python.exe scripts\\make_oura_demo.py            # 14 nights ending 2026-11-22
    .\\venv\\Scripts\\python.exe scripts\\demo_display.py oura --demo
"""
import argparse
import sys
from datetime import date
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from hub.oura_app.demo_data import build  # noqa: E402
from hub.oura_app.data import LocalStore  # noqa: E402

CACHE = ROOT / "data" / "cache" / "sleep_edf"
OUT = ROOT / "tests" / "fixtures" / "oura_demo"


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--nights", type=int, default=14)
    ap.add_argument("--last-day", default="2026-11-22")
    ap.add_argument("--out", type=Path, default=OUT)
    a = ap.parse_args()
    hyps = []
    for s in range(a.nights):
        f = CACHE / f"sc{s:02d}.npz"
        if not f.exists():
            sys.exit(f"missing {f}: run scripts/sleep_edf_baseline.py first to cache Sleep-EDF")
        hyps.append(np.load(f)["y"])
    store = LocalStore(a.out)
    for name, recs in build(hyps, date.fromisoformat(a.last_day)).items():
        store._save(name, recs)                                  # replace, so the set is exactly this build
    print(f"wrote {a.nights} nights to {a.out}")


if __name__ == "__main__":
    main()
