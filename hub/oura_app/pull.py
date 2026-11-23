"""Pull recent Oura data into the local store (REQ-OURA-04/05).

Each run covers the last `days` days (at least REPULL_DAYS = 3, to catch late ring syncs). Oura's answer
replaces what is stored for that window: records are upserted, so running it nightly, or twice, never
duplicates one, and stored records in the window that Oura no longer returns (a deleted or re-issued
sleep period) are removed. Every collection in
config.COLLECTIONS whose scope was granted is pulled; one the sign-in doesn't cover is reported
as "no access" and the rest still go through.
"""
from datetime import date, datetime, time, timedelta, timezone

from .auth import AuthError
from .client import NoAccess, OuraError
from .config import COLLECTIONS, REPULL_DAYS
from .data import iso_utc, normalise_sleep, to_utc

HR_CHUNK_DAYS = 7


def window(today: date, days: int) -> tuple[date, date]:
    days = max(days, REPULL_DAYS)
    return today - timedelta(days=days), today + timedelta(days=1)


def wanted(scopes: str, heartrate: bool = True) -> list[str]:
    granted = set(scopes.split())
    return [n for n, (scope, _) in COLLECTIONS.items() if scope in granted and (heartrate or n != "heartrate")]


def _key(rec: dict) -> str:
    return rec.get("id") or rec.get("day") or rec.get("timestamp")


def _fetch(client, name: str, start: date, end: date) -> dict:
    if name == "heartrate":
        hr, t = {}, datetime.combine(start, time(), timezone.utc)
        stop = datetime.combine(end, time(), timezone.utc)
        while t < stop:
            t2 = min(t + timedelta(days=HR_CHUNK_DAYS), stop)
            for row in client.collection("heartrate", start_datetime=iso_utc(t), end_datetime=iso_utc(t2)):
                hr[iso_utc(to_utc(row["timestamp"]))] = {"bpm": row["bpm"], "source": row.get("source")}
            t = t2
        return hr
    rows = client.collection(name, start_date=start.isoformat(), end_date=end.isoformat())
    if name == "sleep":
        return {r["id"]: normalise_sleep(r) for r in rows if r.get("type") != "deleted"}
    return {_key(r): r for r in rows}


def _in_window(name: str, start: date, end: date):
    """Which stored records the re-pull of [start, end] is the full answer for."""
    if COLLECTIONS[name][1] == "datetime":                  # heart rate: keyed by UTC timestamp
        a, b = iso_utc(datetime.combine(start, time(), timezone.utc)), iso_utc(datetime.combine(end, time(), timezone.utc))
        return lambda key, rec: a <= key < b
    lo, hi = start.isoformat(), end.isoformat()             # Oura's start_date/end_date: days, inclusive
    return lambda key, rec: bool(rec.get("day")) and lo <= rec["day"] <= hi


def pull(client, store, today: date | None = None, days: int = REPULL_DAYS, heartrate: bool = True,
         names: list[str] | None = None) -> dict:
    """Returns {"window": [start, end], <collection>: {new, updated, unchanged} or {"error": msg}}."""
    today = today or datetime.now(timezone.utc).date()
    start, end = window(today, days)
    out = {"window": [start.isoformat(), end.isoformat()]}
    for name in names or wanted(client.s.scopes, heartrate):
        try:
            recs = _fetch(client, name, start, end)            # raises before anything is replaced
            out[name] = store.replace_window(name, recs, _in_window(name, start, end))
        except NoAccess:
            out[name] = {"error": "no access (scope not granted)"}
        except OuraError as e:
            out[name] = {"error": str(e)}
        except AuthError:
            raise                                   # sign-in itself is broken: stop, don't report per collection
    return out
