"""Oura API v2 client: auto-refresh, 401/429 handling, pagination, sandbox mode (REQ-OURA-03/06/07)."""
import time

from . import auth
from .tokens import TokenLock
from .config import (API_BASE, DATA_DIR, MAX_429_RETRIES, MAX_RETRY_AFTER_S, REFRESH_MARGIN_S, SANDBOX_BASE, USER_AGENT,
                     Settings)


class OuraError(RuntimeError):
    pass


class NoAccess(OuraError):
    """The token works but doesn't cover this collection (scope not granted, or not on this account)."""


class OuraClient:
    def __init__(self, settings: Settings, store, http=None, sandbox: bool = False, sleep=time.sleep, now=time.time,
                 lock_path=None):
        if http is None:
            import requests
            http = requests.Session()
        self.s, self.store, self.http, self.sleep, self.now = settings, store, http, sleep, now
        self.base = SANDBOX_BASE if sandbox else API_BASE
        self._fresh = False             # True once this client has refreshed the token itself
        self.lock_path = lock_path or DATA_DIR / ".token.lock"

    def _token(self, force_refresh: bool = False):
        tok = self.store.load()
        if tok is None:
            raise auth.AuthError("not signed in: run `python -m hub.oura_app login` first")
        if not force_refresh and tok.expires_at - self.now() >= REFRESH_MARGIN_S:
            return tok
        with TokenLock(self.lock_path):
            cur = self.store.load() or tok
            if cur.refresh_token != tok.refresh_token and cur.expires_at - self.now() >= REFRESH_MARGIN_S:
                self._fresh = True      # another run refreshed while we waited: use its token
                return cur
            try:
                new = auth.refresh(self.http, self.s, cur, self.store, now=self.now())
            except auth.AuthError as e:
                again = self.store.load()
                if e.code == "invalid_grant" and again and again.refresh_token != cur.refresh_token:
                    self._fresh = True  # spent by a run that didn't hold the lock; its new token is saved
                    return again
                raise
            self._fresh = True
            return new

    def _request(self, path: str, params: dict) -> dict:
        tok, refreshed, waits = self._token(), False, 0
        while True:
            r = self.http.get(f"{self.base}/{path}", params=params, timeout=60,
                              headers={"Authorization": f"Bearer {tok.access_token}", "User-Agent": USER_AGENT})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and not refreshed and not self._fresh:   # expired: refresh once, retry once
                tok, refreshed = self._token(force_refresh=True), True
                continue
            if r.status_code == 401 and self._fresh and not refreshed:
                # The token was refreshed earlier in this run and works elsewhere: a scope problem.
                raise NoAccess(f"{path}: not covered by this sign-in (scope not granted)")
            if r.status_code == 429 and waits < MAX_429_RETRIES:
                try:
                    wait = float(r.headers.get("Retry-After", 60))
                except ValueError:
                    wait = 60.0
                waits += 1
                self.sleep(min(max(wait, 1.0), MAX_RETRY_AFTER_S))
                continue
            if r.status_code == 401:
                # A brand-new token rejected: either the sign-in was revoked or the scope is missing.
                raise NoAccess(f"{path}: rejected even with a fresh token (scope not granted, or sign in again)")
            if r.status_code == 403:
                raise OuraError(f"{path}: HTTP 403 (missing scope, or the Oura membership has expired)")
            raise OuraError(f"{path}: HTTP {r.status_code}")

    def collection(self, path: str, **params) -> list[dict]:
        """All documents of a usercollection endpoint, following next_token."""
        out, params = [], {k: v for k, v in params.items() if v is not None}
        while True:
            body = self._request(path, params)
            out += body.get("data", [])
            nxt = body.get("next_token")
            if not nxt:
                return out
            params = {**params, "next_token": nxt}

    def sleep_periods(self, start_date: str, end_date: str):
        return self.collection("sleep", start_date=start_date, end_date=end_date)

    def daily_sleep(self, start_date: str, end_date: str):
        return self.collection("daily_sleep", start_date=start_date, end_date=end_date)

    def heartrate(self, start_datetime: str, end_datetime: str):
        return self.collection("heartrate", start_datetime=start_datetime, end_datetime=end_datetime)
