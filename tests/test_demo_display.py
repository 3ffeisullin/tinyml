"""The demo display's parser understands every line format firmware/eeg_node prints (task 7d)."""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from demo_display import STAGE_Y, STAGES, parse  # noqa: E402


def test_window_line():
    ev = parse("W 12 3.912 2.130 4.450 2.540 2.730 2.610 0.740 54.3 1.341 0.000")
    assert ev[0] == "win" and ev[1] == 12 and len(ev[2]) == 6
    assert ev[2][2] == 4.45 and ev[3] == 0.74 and ev[4] == 54.3 and ev[5] == 1.341 and ev[6] == 0


def test_out_feat_stat_lines():
    assert parse("OUT 3 N2 -86 -97 4 -108 -97") == ("out", 3, STAGES.index("N2"))
    ev = parse("FEAT 7 29 " + " ".join(["0.5"] * 30))
    assert ev[0] == "feat" and ev[1] == 7 and np.allclose(ev[2], 0.5) and len(ev[2]) == 30
    ev = parse("STAT samples 83751 rate 250.00 Hz missed 0 i2c_errors 0 queue_full 0 timeouts 0 epochs 11")
    assert ev == ("stat", {"samples": 83751, "rate": 250.0, "missed": 0, "i2c_errors": 0, "queue_full": 0})


def test_messages_and_noise():
    assert parse("FAKE PARITY PASS: 11 live windows vs Python")[0] == "msg"
    assert parse("ERR ADC not found at 0x48 (try LIVE FAKE)")[0] == "msg"
    assert parse("EPOCH 5 29") is None and parse("") is None and parse("W 1 2") is None
    assert parse("OUT 1 XX 1 2 3 4 5") is None


def test_hypnogram_rows_cover_every_stage():
    assert sorted(STAGE_Y) == list(range(len(STAGES))) and sorted(STAGE_Y.values()) == [0, 1, 2, 3, 4]
