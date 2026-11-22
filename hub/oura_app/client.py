"""Oura API v2 client: auto-refresh, 401/429 handling, pagination, sandbox mode (REQ-OURA-03/06/07)."""
import time

from . import auth
from .config import (API_BASE, MAX_429_RETRIES, MAX_RETRY_AFTER_S, REFRESH_MARGIN_S, SANDBOX_BASE, USER_AGENT,
                     Settings)


class OuraError(RuntimeError):
    pass


class OuraClient:
    def __init__(self, settings: Settings, store, http=None, sandbox: bool = False, sleep=time.sleep, now=time.time):
        if http is None:
            import requests
            http = requests.Session()
        self.s, self.store, self.http, self.sleep, self.now = settings, store, http, sleep, now
        self.base = SANDBOX_BASE if sandbox else API_BASE

    def _token(self, force_refresh: bool = False):
        tok = self.store.load()
        if tok is None:
            raise auth.AuthError("not signed in: run `python -m hub.oura_app login` first")
        if force_refresh or tok.expires_at - self.now() < REFRESH_MARGIN_S:
            tok = auth.refresh(self.http, self.s, tok, self.store, now=self.now())
        return tok

    def _request(self, path: str, params: dict) -> dict:
        tok, refreshed, waits = self._token(), False, 0
        while True:
            r = self.http.get(f"{self.base}/{path}", params=params, timeout=60,
                              headers={"Authorization": f"Bearer {tok.access_token}", "User-Agent": USER_AGENT})
            if r.status_code == 200:
                return r.json()
            if r.status_code == 401 and not refreshed:        # expired or revoked: refresh once, retry once
                tok, refreshed = self._token(force_refresh=True), True
                continue
            if r.status_code == 429 and waits < MAX_429_RETRIES:
                try:
                    wait = float(r.headers.get("Retry-After", 60))
                except ValueError:
                    wait = 60.0
                waits += 1
                self.sleep(min(max(wait, 1.0), MAX_RETRY_AFTER_S))
                continue
            if r.status_code == 401:
                raise auth.AuthError("Oura rejected the token after a refresh: sign in again")
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
