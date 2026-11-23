"""Per-night stage-minute arithmetic (scripts/stage_minutes_report.py)."""
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from stage_minutes_report import compare_night, night_measures, summarise  # noqa: E402

W, N1, N2, N3, REM = range(5)


def test_minutes_total_sleep_and_deep_share():
    m = night_measures([W, W, N1, N2, N2, N3, N3, REM])  # 30 s epochs
    assert m["W"] == 1.0 and m["N1"] == 0.5 and m["N2"] == 1.0 and m["N3"] == 1.0 and m["REM"] == 0.5
    assert m["TST"] == 3.0                       # wake excluded
    assert m["N3_pct"] == pytest.approx(100 * 2 / 6)


def test_all_wake_night_has_no_sleep():
    m = night_measures([W, W, W])
    assert m["TST"] == 0 and m["N3_pct"] == 0


def test_errors_are_model_minus_experts():
    y = np.array([N2, N2, N2, N3])
    pred = np.array([N2, N3, N3, N3])
    c = compare_night(y, pred)
    assert c["error"]["N3"] == 1.0 and c["error"]["N2"] == -1.0 and c["error"]["TST"] == 0
    assert c["accuracy"] == 0.5


def test_summary_bias_mae_and_worst_night():
    nights = {"A": compare_night(np.array([N3, N3]), np.array([N3, N3])),        # error 0
              "B": compare_night(np.array([N2, N2]), np.array([N3, N3])),        # N3 +1.0 min
              "C": compare_night(np.array([N3, N3, N3]), np.array([N2, N2, N3]))}  # N3 -1.0 min
    s = summarise(nights)["N3"]
    assert s["bias"] == pytest.approx(0.0) and s["mae"] == pytest.approx(2 / 3)
    assert s["worst_night"] == "B" and s["worst_error"] == 1.0
