"""Command line for the Oura app. From the repo root:

    .\\venv\\Scripts\\python.exe -m hub.oura_app login            # once: browser sign-in, tokens to Credential Manager
    .\\venv\\Scripts\\python.exe -m hub.oura_app pull --days 30   # first time; nightly runs use the default 3 days
    .\\venv\\Scripts\\python.exe -m hub.oura_app nights           # table of stored nights
    .\\venv\\Scripts\\python.exe -m hub.oura_app day [--day D]    # everything Oura has for one day
    .\\venv\\Scripts\\python.exe -m hub.oura_app status           # signed in? token expiry? stored nights?
    .\\venv\\Scripts\\python.exe -m hub.oura_app check            # does Oura accept the client ID/secret in .env?
    .\\venv\\Scripts\\python.exe -m hub.oura_app logout           # revoke and delete the tokens
Add --sandbox (before the command) to use Oura's sandbox data instead of the ring's (REQ-OURA-06).
"""
import argparse
import sys
import time
from datetime import datetime, timezone

from . import auth
from .client import OuraClient
from .config import DATA_DIR, REPULL_DAYS, REVOKE_URL, TOKEN_URL, USER_AGENT, ConfigError, load_settings
from .data import LocalStore, day_view, night_summary
from .report import print_day
from .pull import pull
from .tokens import KeyringStore

COLS = [("day", "Day", 10), ("type", "Type", 10), ("start_local", "Bed", 5), ("end_local", "Up", 5),
        ("sleep_min", "Sleep", 6), ("deep_min", "Deep", 5), ("deep_pct", "Deep%", 5), ("light_min", "Light", 6),
        ("rem_min", "REM", 5), ("awake_min", "Awake", 5), ("avg_hrv", "HRV", 4), ("lowest_hr", "HRmin", 5),
        ("has_30s", "30s", 4)]


def print_nights(rows):
    print("  ".join(f"{h:>{w}}" for _, h, w in COLS))
    for r in rows:
        print("  ".join(f"{('' if r[k] is None else r[k])!s:>{w}}" for k, _, w in COLS))
    print("(minutes; Bed/Up in local time; 30s = 30-second hypnogram present)")


def main(argv=None):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    ap = argparse.ArgumentParser(prog="python -m hub.oura_app")
    ap.add_argument("--sandbox", action="store_true", help="use Oura's sandbox endpoints")
    sub = ap.add_subparsers(dest="cmd", required=True)
    lg = sub.add_parser("login"); lg.add_argument("--no-browser", action="store_true")
    lg.add_argument("--timeout", type=float, default=300)
    pl = sub.add_parser("pull"); pl.add_argument("--days", type=int, default=REPULL_DAYS)
    pl.add_argument("--no-heartrate", action="store_true")
    nt = sub.add_parser("nights"); nt.add_argument("--all", action="store_true", help="include naps and rests")
    dy = sub.add_parser("day", help="everything stored for one day"); dy.add_argument("--day", help="YYYY-MM-DD")
    sub.add_parser("status"); sub.add_parser("logout"); sub.add_parser("check", help="test the client ID/secret")
    a = ap.parse_args(argv)

    store = KeyringStore()
    local = LocalStore(DATA_DIR / ("sandbox" if a.sandbox else "live"))
    try:
        if a.cmd == "nights":
            rows = [night_summary(r) for r in local.sleep() if a.all or r.get("type") == "long_sleep"]
            print_nights(rows) if rows else print("No nights stored yet: run `pull` first.")
            return 0
        if a.cmd == "day":
            print_day(day_view(local, a.day))
            return 0
        if a.cmd == "status":
            tok = store.load()
            if tok is None:
                print("Not signed in.")
            else:
                left = (tok.expires_at - time.time()) / 3600
                print(f"Signed in; access token {'valid for %.1f h' % left if left > 0 else 'expired (refreshes on next pull)'}.")
            print(f"Stored: {len(local.sleep())} sleep periods in {local.root}")
            return 0
        s = load_settings()
        import requests
        http = requests.Session()
        if a.cmd == "check":
            # A refresh with a dummy token: Oura answers invalid_client if the ID/secret pair is wrong,
            # invalid_grant if the pair is right (the dummy token is, of course, rejected).
            r = http.post(TOKEN_URL, data={"grant_type": "refresh_token", "refresh_token": "dummy",
                                           "client_id": s.client_id, "client_secret": s.client_secret},
                          headers={"User-Agent": USER_AGENT}, timeout=30)
            try:
                err = r.json().get("error", "")
            except ValueError:
                err = ""
            if err == "invalid_client":
                print("Client ID/secret rejected by Oura: re-copy the secret into .env.")
                return 1
            print(f"Client ID and secret accepted by Oura (HTTP {r.status_code} {err} for the dummy token is expected).")
            return 0
        if a.cmd == "login":
            auth.login(http, s, store, open_browser=not a.no_browser, timeout=a.timeout)
            print("Signed in. Tokens saved in Windows Credential Manager (tinyml-oura).")
        elif a.cmd == "pull":
            res = pull(OuraClient(s, store, http, sandbox=a.sandbox), local, days=a.days, heartrate=not a.no_heartrate)
            print(f"Pulled {res['window'][0]} to {res['window'][1]} ({'sandbox' if a.sandbox else 'live'}) "
                  f"at {datetime.now(timezone.utc):%Y-%m-%d %H:%M} UTC")
            for k, c in res.items():
                if k == "window":
                    continue
                print(f"  {k:25s} " + (c["error"] if "error" in c else
                                         f"{c['new']} new, {c['updated']} updated, {c['unchanged']} unchanged"))
        elif a.cmd == "logout":
            tok = store.load()
            if tok:
                http.post(REVOKE_URL, params={"access_token": tok.access_token},
                          headers={"User-Agent": USER_AGENT}, timeout=30)
            store.delete()
            print("Signed out; tokens revoked and deleted.")
        return 0
    except (ConfigError, auth.AuthError, RuntimeError) as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
