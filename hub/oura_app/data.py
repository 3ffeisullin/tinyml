"""Local storage and night summaries for Oura data (REQ-OURA-04/05).

Until the InfluxDB hub exists (task 5b), records are kept as JSON under data/oura/<live|sandbox>/,
keyed by Oura's document id (sleep, daily sleep) or by UTC timestamp (heart rate), so re-pulling a
day replaces its records instead of duplicating them. Every timestamp is stored in UTC, with the
original UTC offset kept in `utc_offset` so local clock times can still be shown.
"""
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

OURA_STAGE = {"1": "deep", "2": "light", "3": "REM", "4": "awake"}
# REQ-OURA-08: weak labels for our 5 stages (light covers N1 and N2).
OURA_TO_AASM = {"deep": "N3", "light": "N1/N2", "REM": "REM", "awake": "W"}


def to_utc(ts: str) -> datetime:
    """ISO-8601 with an offset (or Z) -> aware UTC datetime. A naive timestamp is an error."""
    dt = datetime.fromisoformat(ts)
    if dt.tzinfo is None:
        raise ValueError(f"timestamp without a UTC offset: {ts!r}")
    return dt.astimezone(timezone.utc)


def iso_utc(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def offset_of(ts: str) -> str:
    off = datetime.fromisoformat(ts).utcoffset()
    mins = int(off.total_seconds() // 60)
    return f"{'+' if mins >= 0 else '-'}{abs(mins) // 60:02d}:{abs(mins) % 60:02d}"


def normalise_sleep(rec: dict) -> dict:
    r = dict(rec)
    r["utc_offset"] = offset_of(rec["bedtime_start"])
    for k in ("bedtime_start", "bedtime_end"):
        r[k] = iso_utc(to_utc(rec[k]))
    for k in ("heart_rate", "hrv"):
        if isinstance(rec.get(k), dict) and rec[k].get("timestamp"):
            r[k] = {**rec[k], "timestamp": iso_utc(to_utc(rec[k]["timestamp"]))}
    return r


def hypnogram(rec: dict, resolution: int = 30) -> list[tuple[datetime, str]]:
    """[(UTC start of each interval, 'deep'|'light'|'REM'|'awake')] from sleep_phase_30_sec or _5_min."""
    phases = rec.get("sleep_phase_30_sec" if resolution == 30 else "sleep_phase_5_min") or ""
    t0 = to_utc(rec["bedtime_start"])
    return [(t0 + timedelta(seconds=i * resolution), OURA_STAGE.get(c, "?")) for i, c in enumerate(phases)]


def night_summary(rec: dict) -> dict:
    m = lambda k: round((rec.get(k) or 0) / 60, 1)  # noqa: E731
    tst = m("total_sleep_duration")
    off = rec.get("utc_offset", "+00:00")
    tz = timezone(timedelta(hours=int(off[:3]), minutes=int(off[0] + off[4:])))
    return {"day": rec.get("day"), "type": rec.get("type"),
            "start_local": to_utc(rec["bedtime_start"]).astimezone(tz).strftime("%H:%M"),
            "end_local": to_utc(rec["bedtime_end"]).astimezone(tz).strftime("%H:%M"),
            "in_bed_min": m("time_in_bed"), "sleep_min": tst, "deep_min": m("deep_sleep_duration"),
            "light_min": m("light_sleep_duration"), "rem_min": m("rem_sleep_duration"), "awake_min": m("awake_time"),
            "deep_pct": round(100 * m("deep_sleep_duration") / tst, 1) if tst else 0.0,
            "efficiency": rec.get("efficiency"), "avg_hrv": rec.get("average_hrv"),
            "lowest_hr": rec.get("lowest_heart_rate"), "has_30s": bool(rec.get("sleep_phase_30_sec"))}


class LocalStore:
    def __init__(self, root: Path):
        self.root = Path(root)

    def load(self, name: str) -> dict:
        return self._load(name)

    def _load(self, name):
        f = self.root / f"{name}.json"
        return json.loads(f.read_text(encoding="utf-8")) if f.exists() else {}

    def _save(self, name, d):
        self.root.mkdir(parents=True, exist_ok=True)
        tmp = self.root / f"{name}.json.tmp"
        tmp.write_text(json.dumps(d, indent=1, sort_keys=True), encoding="utf-8")
        tmp.replace(self.root / f"{name}.json")

    def upsert(self, name: str, records: dict) -> dict:
        """records: key -> record. Returns counts of new / updated / unchanged."""
        d, c = self._load(name), {"new": 0, "updated": 0, "unchanged": 0}
        for k, v in records.items():
            c["new" if k not in d else "unchanged" if d[k] == v else "updated"] += 1
            d[k] = v
        self._save(name, d)
        return c

    def replace_window(self, name: str, records: dict, in_window) -> dict:
        """Make the re-pulled window match Oura's answer: upsert `records` and drop stored records for which
        `in_window(key, record)` is true but Oura no longer returned them (deleted or re-issued sleep periods).
        Returns counts of new / updated / unchanged / removed."""
        d = self._load(name)
        gone = [k for k, v in d.items() if k not in records and in_window(k, v)]
        for k in gone:
            del d[k]
        self._save(name, d)
        c = self.upsert(name, records)
        c["removed"] = len(gone)
        return c

    def sleep(self) -> list[dict]:
        return sorted(self._load("sleep").values(), key=lambda r: r["bedtime_start"])

    def daily_sleep(self) -> dict:
        return self._load("daily_sleep")

    def heartrate(self) -> dict:
        return self._load("heartrate")


def series(rec: dict, key: str) -> list[tuple[datetime, float]]:
    """A sleep period's 5-min series ('heart_rate' or 'hrv') as [(UTC time, value)], gaps dropped."""
    s = rec.get(key) or {}
    if not s.get("items"):
        return []
    t0, step = to_utc(s["timestamp"]), float(s.get("interval", 300))
    return [(t0 + timedelta(seconds=i * step), float(v)) for i, v in enumerate(s["items"]) if v is not None]


def _by_day(store: LocalStore, name: str, day: str):
    rows = [r for r in store.load(name).values() if r.get("day") == day]
    return max(rows, key=lambda r: r.get("timestamp") or "", default=None)


def days_available(store: LocalStore) -> list[str]:
    return sorted({r["day"] for r in store.sleep() if r.get("type") == "long_sleep" and r.get("day")})


def day_view(store: LocalStore, day: str | None = None) -> dict:
    """Everything stored for one Oura day (the night that ends on it, plus that day's summaries).

    Missing collections come back as None, so a display can show what exists."""
    days = days_available(store)
    day = day or (days[-1] if days else None)
    nights = [r for r in store.sleep() if r.get("day") == day and r.get("type") == "long_sleep"]
    night = max(nights, key=lambda r: r.get("total_sleep_duration") or 0, default=None)
    hr = {}
    if night:
        a, b = to_utc(night["bedtime_start"]), to_utc(night["bedtime_end"])
        hr = {k: v for k, v in store.heartrate().items() if a <= to_utc(k) <= b}
    v = {"day": day, "days": days, "night": night,
         "summary": night_summary(night) if night else None,
         "hypnogram": hypnogram(night) if night and night.get("sleep_phase_30_sec") else
                      hypnogram(night, 300) if night else [],
         "hr": series(night, "heart_rate") if night else [], "hrv": series(night, "hrv") if night else [],
         "hr_samples": sorted((to_utc(k), x["bpm"]) for k, x in hr.items()),
         "trend": [night_summary(r) for r in store.sleep() if r.get("type") == "long_sleep"]}
    for name in ("daily_sleep", "daily_readiness", "daily_activity", "daily_stress", "daily_resilience",
                 "daily_spo2", "daily_cardiovascular_age", "vO2_max", "sleep_time"):
        v[name] = _by_day(store, name, day) if day else None
    return v
