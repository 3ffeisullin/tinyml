"""Oura demo nights (Sleep-EDF stages, simulated heart rate/HRV) and the Oura screen's display helpers."""
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np

from hub.oura_app.data import LocalStore, day_view, hypnogram
from hub.oura_app.demo_data import build, night_from_hypnogram
from hub.oura_app.report import day_lines, hm

ROOT = Path(__file__).resolve().parents[1]
FIXTURE = ROOT / "tests" / "fixtures" / "oura_demo"


def _toy_night():
    # 30 min wake, then cycles of N1, N2, N3, N2, REM, a 10 min wake bout, 30 min wake at the end
    cycle = [1] * 10 + [2] * 40 + [3] * 40 + [2] * 20 + [4] * 30
    return np.array([0] * 60 + cycle * 2 + [0] * 20 + cycle * 2 + [0] * 60)


def test_night_has_consistent_durations_and_stages():
    y = _toy_night()
    rec = night_from_hypnogram(y, date(2026, 11, 22), np.random.default_rng(1))
    n = len(rec["sleep_phase_30_sec"])
    assert rec["time_in_bed"] == n * 30
    assert rec["total_sleep_duration"] + rec["awake_time"] == rec["time_in_bed"]
    assert rec["deep_sleep_duration"] == 4 * 40 * 30                      # every N3 epoch kept, as deep
    assert rec["synthetic"] and rec["type"] == "long_sleep" and rec["utc_offset"] == "-06:00"
    assert rec["bedtime_start"].endswith("Z") and rec["day"] == "2026-11-22"
    end = datetime.fromisoformat(rec["bedtime_end"].replace("Z", "+00:00")).astimezone(timezone(timedelta(hours=-6)))
    assert end.date() == date(2026, 11, 22)                                  # the night ends on its day
    assert len(hypnogram(rec)) == n
    assert len(rec["heart_rate"]["items"]) == n // 10 == len(rec["hrv"]["items"])


def test_heart_rate_and_hrv_follow_the_stages():
    y = _toy_night()
    rec = night_from_hypnogram(y, date(2026, 11, 22), np.random.default_rng(2))
    codes, hr, hrv = rec["sleep_phase_30_sec"], rec["heart_rate"]["items"], rec["hrv"]["items"]
    blocks = [max("1234", key=codes[i * 10:(i + 1) * 10].count) for i in range(len(hr))]
    mean = lambda xs, c: np.mean([x for x, b in zip(xs, blocks) if b == c])  # noqa: E731
    assert mean(hr, "1") < mean(hr, "4")                                     # deep slower than awake
    assert mean(hrv, "1") > mean(hrv, "3")                                   # deep HRV above REM
    assert rec["lowest_heart_rate"] == min(hr)


def test_gap_and_determinism():
    y = _toy_night()
    a = night_from_hypnogram(y, date(2026, 11, 22), np.random.default_rng(3), gap=True)
    b = night_from_hypnogram(y, date(2026, 11, 22), np.random.default_rng(3), gap=True)
    assert a == b
    assert None in a["heart_rate"]["items"]
    out = build([y, y, y], date(2026, 11, 22))
    assert sorted(r["day"] for r in out["sleep"].values()) == ["2026-11-20", "2026-11-21", "2026-11-22"]
    assert len(out["daily_sleep"]) == len(out["daily_readiness"]) == 3


def test_committed_fixture_reads_like_pulled_data():
    v = day_view(LocalStore(FIXTURE))
    assert len(v["days"]) == 14 and v["day"] == "2026-11-22"
    assert len(v["trend"]) == 14 and len({r["deep_min"] for r in v["trend"]}) > 10   # nights differ
    assert v["hr"] and v["hrv"] and len(v["hypnogram"]) > 600
    assert v["daily_sleep"]["score"] and v["daily_readiness"]["score"]
    for name in ("sleep", "daily_sleep", "daily_readiness"):
        assert all(r.get("synthetic") for r in LocalStore(FIXTURE).load(name).values())


def test_hours_and_minutes():
    assert hm(44) == "44 min" and hm(60) == "1 h 00 min" and hm(498.0) == "8 h 18 min"
    rows = dict(day_lines(day_view(LocalStore(FIXTURE))))
    assert rows["In bed"].endswith(" min") and " h " in rows["In bed"]


def test_number_formatting():
    v = {"summary": None, "night": {"latency": 1500, "average_breath": 12.345},     # invented values
         "daily_activity": {"steps": 12345, "total_calories": 2345},
         "daily_stress": {"stress_high": 0, "recovery_high": 5400}, "hr_samples": []}
    rows = dict(day_lines(v))
    assert rows["Time to fall asleep"] == "25 min"
    assert rows["Breathing rate"] == "12.3 /min"
    assert rows["Steps"] == "12,345" and rows["Total calories"] == "2,345 kcal"
    assert rows["High stress"] == "0 min" and rows["High recovery"] == "1 h 30 min"


def test_line_breaks_at_gaps_and_screen_renders(tmp_path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    sys.path.insert(0, str(ROOT / "scripts"))
    import demo_display as dd

    t0 = datetime(2026, 11, 22, 5, tzinfo=timezone.utc)
    ts = [t0 + timedelta(minutes=5 * k) for k in (0, 1, 2, 6, 7)]
    bt, by = dd._break_gaps(ts, [50, 51, 52, 53, 54])
    assert len(bt) == 6 and np.isnan(by[3]) and by[4] == 53

    for day in ("2026-11-21", "2026-11-22"):                              # 11-21 has a heart-rate gap
        fig = plt.figure(figsize=(14, 7.8))
        dd.OuraView(fig, day_view(LocalStore(FIXTURE), day), dd.DEMO_SOURCE)
        fig.savefig(tmp_path / f"{day}.png")
        plt.close(fig)
