"""Pull recent Oura data into the local store (REQ-OURA-04/05).

Each run covers the last `days` days (at least REPULL_DAYS = 3, to catch late ring syncs) and
upserts, so running it nightly, or twice, never duplicates a night.
"""
from datetime import date, datetime, time, timedelta, timezone

from .config import REPULL_DAYS
from .data import iso_utc, normalise_sleep, to_utc

HR_CHUNK_DAYS = 7


def window(today: date, days: int) -> tuple[date, date]:
    days = max(days, REPULL_DAYS)
    return today - timedelta(days=days), today + timedelta(days=1)


def pull(client, store, today: date | None = None, days: int = REPULL_DAYS, heartrate: bool = True) -> dict:
    today = today or datetime.now(timezone.utc).date()
    start, end = window(today, days)
    s, e = start.isoformat(), end.isoformat()
    sleep = {r["id"]: normalise_sleep(r) for r in client.sleep_periods(s, e) if r.get("type") != "deleted"}
    daily = {r["id"]: r for r in client.daily_sleep(s, e)}
    out = {"window": [s, e], "sleep": store.upsert("sleep", sleep), "daily_sleep": store.upsert("daily_sleep", daily)}
    if heartrate:
        hr, t = {}, datetime.combine(start, time(), timezone.utc)
        stop = datetime.combine(end, time(), timezone.utc)
        while t < stop:
            t2 = min(t + timedelta(days=HR_CHUNK_DAYS), stop)
            for row in client.heartrate(iso_utc(t), iso_utc(t2)):
                hr[iso_utc(to_utc(row["timestamp"]))] = {"bpm": row["bpm"], "source": row.get("source")}
            t = t2
        out["heartrate"] = store.upsert("heartrate", hr)
    return out
