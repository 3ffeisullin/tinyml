"""Realistic sample nights in Oura's format, for display work, tests and demo rehearsal (no personal data).

Oura's sandbox nights are a few minutes long with no hypnogram, so they can't show what the Oura screen
looks like on a real night. These nights take their sleep stages from Sleep-EDF (PhysioNet, ODC-By 1.0):
one expert-scored night per Sleep-EDF subject, 30 s epochs mapped to Oura's stages (W -> awake,
N1/N2 -> light, N3 -> deep, REM -> REM). Everything else is simulated from those stages with a seeded
random generator: heart rate and HRV (5-min values that follow the stages: heart rate lower and HRV higher
in deep sleep, both changeable in REM and when awake), breathing rate, scores and contributors. The
scores are simple stand-ins, not Oura's formulas. Every record carries "synthetic": true.

Records are written in the stored form (`normalise_sleep`: UTC timestamps plus `utc_offset`), so
`LocalStore` and `day_view` read them like pulled data.
"""
from datetime import date, datetime, timedelta, timezone

import numpy as np

from .data import normalise_sleep

AASM_TO_OURA_CODE = {0: "4", 1: "2", 2: "2", 3: "1", 4: "3"}     # W, N1, N2, N3, REM -> Oura phase codes
CODE_STAGE = {"1": "deep", "2": "light", "3": "REM", "4": "awake"}
HR_OFFSET = {"deep": -5.0, "light": 0.0, "REM": 3.0, "awake": 9.0}       # bpm relative to the night's base
HRV_OFFSET = {"deep": 18.0, "light": 5.0, "REM": -8.0, "awake": -15.0}   # ms relative to the night's base
TZ = timezone(timedelta(hours=-6))                                        # US Central, standard time
EPOCH_S = 30


def _clip(x, lo=1, hi=100):
    return int(max(lo, min(hi, round(x))))


def _ar1(rng, n, sd, rho=0.9):
    e = rng.normal(0, sd * np.sqrt(1 - rho ** 2), n)
    out = np.empty(n)
    acc = rng.normal(0, sd)
    for i in range(n):
        acc = rho * acc + e[i]
        out[i] = acc
    return out


def _five_min(values: np.ndarray, decimals: int) -> list:
    k = 300 // EPOCH_S
    n = len(values) // k
    return [round(float(values[i * k:(i + 1) * k].mean()), decimals) for i in range(n)]


def night_from_hypnogram(y, day: date, rng: np.random.Generator, gap: bool = False) -> dict:
    """One Oura-style sleep record (stored form) from AASM labels y (0..4 per 30 s epoch, W at both ends).

    `day` is the morning the night ends on (Oura's `day`). `gap` drops a stretch of 5-min heart-rate and
    HRV values, as Oura does when the ring loses contact."""
    y = np.asarray(y)
    sleep_idx = np.flatnonzero(y != 0)
    if not len(sleep_idx):
        raise ValueError("hypnogram has no sleep")
    a = max(0, int(sleep_idx[0]) - int(rng.integers(10, 40)))                # in bed 5-20 min before sleep
    b = min(len(y), int(sleep_idx[-1]) + 1 + int(rng.integers(6, 30)))       # up 3-15 min after waking
    codes = "".join(AASM_TO_OURA_CODE[int(s)] for s in y[a:b])
    stages = [CODE_STAGE[c] for c in codes]
    n = len(codes)

    start_local = datetime.combine(day - timedelta(days=1), datetime.min.time(), TZ) + timedelta(
        hours=22, minutes=int(rng.integers(0, 100)))
    end_local = start_local + timedelta(seconds=n * EPOCH_S)

    t = np.arange(n) / n
    hr_base, hrv_base = rng.uniform(50, 62), rng.uniform(38, 72)
    hr = hr_base + np.array([HR_OFFSET[s] for s in stages]) - 4 * np.minimum(t * 2, 1) + _ar1(rng, n, 1.5)
    hrv = hrv_base + np.array([HRV_OFFSET[s] for s in stages]) + _ar1(rng, n, 7.0, 0.8)
    hr5, hrv5 = _five_min(hr, 0), _five_min(np.maximum(hrv, 8), 0)
    if gap and len(hr5) > 30:
        g0 = int(rng.integers(len(hr5) // 3, 2 * len(hr5) // 3))
        for i in range(g0, g0 + int(rng.integers(3, 7))):
            hr5[i] = hrv5[i] = None

    count = {s: stages.count(s) * EPOCH_S for s in ("deep", "light", "REM", "awake")}
    tst = count["deep"] + count["light"] + count["REM"]
    tib = n * EPOCH_S
    latency = int(sleep_idx[0] - a) * EPOCH_S
    phase5 = "".join(max("1234", key=codes[i:i + 10].count) for i in range(0, n - n % 10, 10))
    valid_hr = [v for v in hr5 if v is not None]
    valid_hrv = [v for v in hrv5 if v is not None]
    wake_bouts = sum(1 for i in range(1, n) if stages[i] == "awake" and stages[i - 1] != "awake")
    rec = {
        "id": f"demo-{day.isoformat()}", "day": day.isoformat(), "type": "long_sleep", "synthetic": True,
        "bedtime_start": start_local.isoformat(), "bedtime_end": end_local.isoformat(),
        "sleep_phase_30_sec": codes, "sleep_phase_5_min": phase5,
        "time_in_bed": tib, "total_sleep_duration": tst, "deep_sleep_duration": count["deep"],
        "light_sleep_duration": count["light"], "rem_sleep_duration": count["REM"], "awake_time": count["awake"],
        "efficiency": _clip(100 * tst / tib), "latency": latency,
        "average_heart_rate": round(float(np.mean(valid_hr)), 1), "lowest_heart_rate": int(min(valid_hr)),
        "average_hrv": int(round(np.mean(valid_hrv))), "average_breath": round(float(rng.uniform(12.5, 16.0)), 1),
        "restless_periods": int(wake_bouts * 6 + rng.integers(20, 120)),
        "heart_rate": {"interval": 300.0, "items": hr5, "timestamp": start_local.isoformat()},
        "hrv": {"interval": 300.0, "items": hrv5, "timestamp": start_local.isoformat()},
    }
    return normalise_sleep(rec)


def daily_from_night(rec: dict) -> tuple[dict, dict]:
    """Stand-in daily_sleep and daily_readiness records for a night (simple formulas, not Oura's)."""
    h = lambda k: (rec.get(k) or 0) / 3600  # noqa: E731
    tst = h("total_sleep_duration")
    c = {"deep_sleep": _clip(100 * h("deep_sleep_duration") / 1.5), "efficiency": _clip(rec["efficiency"] * 1.05),
         "latency": _clip(100 - max(0, rec["latency"] / 60 - 15) * 3),
         "rem_sleep": _clip(100 * h("rem_sleep_duration") / 1.75), "restfulness": _clip(100 - rec["restless_periods"] / 4),
         "timing": 80, "total_sleep": _clip(100 * tst / 8)}
    score = _clip(0.35 * c["total_sleep"] + 0.1 * c["efficiency"] + 0.1 * c["restfulness"] + 0.15 * c["rem_sleep"]
                  + 0.15 * c["deep_sleep"] + 0.1 * c["latency"] + 0.05 * c["timing"])
    ts = rec["bedtime_end"]
    sleep = {"id": f"demo-sleep-{rec['day']}", "day": rec["day"], "score": score, "contributors": c,
             "timestamp": ts, "synthetic": True}
    rc = {"previous_night": score, "sleep_balance": _clip(score + 5), "resting_heart_rate": _clip(150 - 1.6 * rec["lowest_heart_rate"]),
          "hrv_balance": _clip(40 + rec["average_hrv"] * 0.7), "recovery_index": _clip(70 + rec["average_hrv"] / 3)}
    ready = {"id": f"demo-readiness-{rec['day']}", "day": rec["day"], "score": _clip(np.mean(list(rc.values()))),
             "contributors": rc, "temperature_deviation": round(0.1 * (score - 75) / 10, 2),
             "timestamp": ts, "synthetic": True}
    return sleep, ready


def build(hypnograms: list, last_day: date, seed: int = 27) -> dict[str, dict]:
    """{collection: {key: record}} for consecutive nights ending on `last_day`, one per hypnogram."""
    rng = np.random.default_rng(seed)
    out = {"sleep": {}, "daily_sleep": {}, "daily_readiness": {}}
    n = len(hypnograms)
    for i, y in enumerate(hypnograms):
        day = last_day - timedelta(days=n - 1 - i)
        rec = night_from_hypnogram(y, day, rng, gap=(i % 5 == 2))
        ds, dr = daily_from_night(rec)
        out["sleep"][rec["id"]] = rec
        out["daily_sleep"][ds["id"]] = ds
        out["daily_readiness"][dr["id"]] = dr
    return out
