"""Signal-quality flags (REQ-FEAT-08 flags) and the live view's banner."""
import sys
from pathlib import Path

from eegml import config
from eegml.quality import BAD, NONE, OK, WARN, QualityTracker, classify_window

GOOD = (60.0, 0.05, 0.0)           # ptp uV, mains ratio, clip fraction: ordinary forehead EEG


def test_classify_each_failure():
    assert classify_window(*GOOD).level == OK
    assert classify_window(0.5, 0.05, 0.0).level == BAD and "flat" in classify_window(0.5, 0.05, 0.0).reasons[0]
    assert classify_window(250, 0.05, 0.0).level == WARN                               # a blink
    assert classify_window(900, 0.05, 0.0).level == BAD
    assert classify_window(60, 0.8, 0.0).level == WARN
    off = classify_window(60, 5.0, 0.0)
    assert off.level == BAD and "mains" in off.reasons[0]
    assert classify_window(60, 0.05, 0.002).level == WARN
    assert classify_window(60, 0.05, 0.2).level == BAD


def test_worst_reason_first():
    wq = classify_window(250, 5.0, 0.0)                     # blink-size swing and heavy hum
    assert wq.level == BAD and "mains" in wq.reasons[0] and len(wq.reasons) == 2


def test_one_blink_does_not_raise_the_alarm_but_sustained_bad_does():
    q = QualityTracker()
    assert q.status(0)[0] == NONE
    for i in range(5):
        q.add_window(i + 1, *GOOD, now=i)
    assert q.status(4) == (OK, "Signal OK")
    q.add_window(6, 900, 0.05, 0.0, now=5)                  # one huge swing
    assert q.status(5)[0] == WARN
    for i in range(6, 9):
        q.add_window(i + 1, 60, 5.0, 0.0, now=i)            # electrode lifts: hum dominates
    level, msg = q.status(8)
    assert level == BAD and msg.startswith("Mains hum")
    for i in range(9, 14):
        q.add_window(i + 1, *GOOD, now=i)
    assert q.status(13)[0] == OK                            # recovers after 5 good windows


def test_no_data_and_missed_samples():
    q = QualityTracker()
    q.add_window(1, *GOOD, now=100.0)
    assert q.status(100.0 + config.QUALITY.stale_s + 1)[0] == BAD
    q.add_stat(0, now=100.0)
    q.add_stat(3, now=100.5)
    level, msg = q.status(101.0)
    assert level == WARN and "missed" in msg


def test_epochs_mostly_bad_are_marked():
    q = QualityTracker()
    for t in range(1, 31):                                  # epoch 0 good
        q.add_window(t, *GOOD, now=t)
    for t in range(31, 61):                                 # epoch 1: 20 of 30 windows bad
        q.add_window(t, *(GOOD if t % 3 == 0 else (60, 5.0, 0.0)), now=t)
    assert q.bad_epochs() == [1]


def test_live_view_banner_and_shading(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
    import demo_display as dd

    fig = plt.figure(figsize=(14, 7.8))
    v = dd.LiveView(fig, "fake")
    v.redraw()
    assert "Waiting" in v.banner.get_text()
    for t in range(1, 40):
        bad = 20 <= t < 30
        v.on(("win", float(t), [3.0] * 6, 0.3, 60.0, 5.0 if bad else 0.05, 0.0))
        v.on(("out", t // 30, 2)) if t % 30 == 0 else None
        if t == 29:
            v.redraw()
            assert "Bad signal" in v.banner.get_text() and "mains" in v.reason.get_text().lower()
            assert v._shades                                     # bad stretch tinted
    v.redraw()
    assert v.banner.get_text().endswith("Signal OK") and v.reason.get_text() == ""
    fig.savefig(tmp_path / "live.png")
    plt.close(fig)
