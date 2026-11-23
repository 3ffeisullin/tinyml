"""Oura app (task 5, REQ-OURA-01..07) against a fake HTTP session: no network, no real tokens."""
import base64
import hashlib
from datetime import date, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from hub.oura_app import auth
from hub.oura_app.client import NoAccess, OuraClient, OuraError
from hub.oura_app.config import (API_BASE, SANDBOX_BASE, TOKEN_URL, ConfigError, Settings, load_settings, parse_env)
from hub.oura_app.data import LocalStore, day_view, hypnogram, night_summary, normalise_sleep, series, to_utc
from hub.oura_app.pull import pull, wanted, window
from hub.oura_app.tokens import KeyringStore, MemoryStore, Token

S = Settings("client-id-123", "s3cret-value", "http://localhost:8080/callback", "daily heartrate")
NOW = 1_800_000_000.0


class Resp:
    def __init__(self, status=200, body=None, headers=None):
        self.status_code, self._body, self.headers = status, body or {}, headers or {}

    def json(self):
        return self._body


class FakeHTTP:
    """Replays queued responses; records every call."""

    def __init__(self, *responses):
        self.queue, self.calls = list(responses), []

    def _next(self, method, url, **kw):
        self.calls.append((method, url, kw))
        return self.queue.pop(0)

    def get(self, url, **kw):
        return self._next("GET", url, **kw)

    def post(self, url, **kw):
        return self._next("POST", url, **kw)


def token(expires_at=NOW + 3600):
    return Token("acc-old", "ref-old", expires_at)


TOKEN_BODY = {"access_token": "acc-new", "refresh_token": "ref-new", "expires_in": 86400, "token_type": "bearer"}


# --- settings ---------------------------------------------------------------------------------
def test_settings_never_show_the_secret(tmp_path):
    assert "s3cret" not in repr(S) and "s3cret" not in str(S)
    f = tmp_path / ".env"
    f.write_text("# c\nOURA_CLIENT_ID=abc\nOURA_CLIENT_SECRET=\"xyz\"\n", encoding="utf-8")
    s = load_settings(f)
    assert s.client_id == "abc" and s.client_secret == "xyz" and s.redirect_uri.endswith(":8080/callback")
    f.write_text("OURA_CLIENT_ID=abc\nOURA_CLIENT_SECRET=\n", encoding="utf-8")
    with pytest.raises(ConfigError, match="OURA_CLIENT_SECRET"):
        load_settings(f)
    assert parse_env("A = 1\nB='two'\nnot a line") == {"A": "1", "B": "two"}


# --- sign-in (REQ-OURA-01/02) -----------------------------------------------------------------
def test_authorize_url_has_minimum_scopes_state_and_pkce():
    verifier, challenge = auth.pkce_pair()
    assert challenge == base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    q = parse_qs(urlparse(auth.authorize_url(S, "st4te", challenge)).query)
    assert q["response_type"] == ["code"] and q["client_id"] == ["client-id-123"]
    assert q["scope"] == ["daily heartrate"] and q["redirect_uri"] == ["http://localhost:8080/callback"]
    assert q["state"] == ["st4te"] and q["code_challenge_method"] == ["S256"]
    assert "s3cret" not in auth.authorize_url(S, "x", challenge)


def test_callback_checks_state_and_denial():
    assert auth.parse_callback("/callback?code=abc&state=s1", "s1") == "abc"
    with pytest.raises(auth.AuthError, match="state"):
        auth.parse_callback("/callback?code=abc&state=evil", "s1")
    with pytest.raises(auth.AuthError, match="access_denied"):
        auth.parse_callback("/callback?error=access_denied&state=s1", "s1")


def test_code_exchange_form_and_expiry():
    http = FakeHTTP(Resp(200, TOKEN_BODY))
    t = auth.exchange_code(http, S, "the-code", "the-verifier", now=NOW)
    method, url, kw = http.calls[0]
    assert method == "POST" and url == TOKEN_URL
    assert kw["data"] == {"grant_type": "authorization_code", "code": "the-code", "redirect_uri": S.redirect_uri,
                          "code_verifier": "the-verifier", "client_id": S.client_id, "client_secret": S.client_secret}
    assert kw["headers"]["User-Agent"]
    assert t.access_token == "acc-new" and t.expires_at == NOW + 86400


def test_failed_token_request_does_not_leak_body():
    http = FakeHTTP(Resp(400, {"error": "invalid_grant", "detail": "s3cret-value"}))
    with pytest.raises(auth.AuthError) as e:
        auth.exchange_code(http, S, "c", "v", now=NOW)
    assert "invalid_grant" in str(e.value) and "s3cret" not in str(e.value)


# --- tokens (REQ-OURA-03) ---------------------------------------------------------------------
def test_refresh_saves_the_new_single_use_refresh_token():
    store = MemoryStore(token())
    auth.refresh(FakeHTTP(Resp(200, TOKEN_BODY)), S, store.load(), store, now=NOW)
    assert store.token.refresh_token == "ref-new" and store.token.access_token == "acc-new"


def test_keyring_store_round_trip_and_hidden_repr():
    class FakeKeyring:
        def __init__(self):
            self.d = {}

        def get_password(self, s, u):
            return self.d.get((s, u))

        def set_password(self, s, u, p):
            self.d[(s, u)] = p

        def delete_password(self, s, u):
            del self.d[(s, u)]

    st = KeyringStore(backend=FakeKeyring())
    assert st.load() is None
    st.save(token())
    assert st.load() == token() and st.service == "tinyml-oura"
    assert "acc-old" not in repr(st.load())
    st.delete()
    assert st.load() is None


def test_token_refreshed_before_expiry():
    store = MemoryStore(token(expires_at=NOW + 60))           # inside the 5-min margin
    http = FakeHTTP(Resp(200, TOKEN_BODY), Resp(200, {"data": [], "next_token": None}))
    OuraClient(S, store, http, now=lambda: NOW).collection("sleep")
    assert http.calls[0][1] == TOKEN_URL
    assert http.calls[1][2]["headers"]["Authorization"] == "Bearer acc-new"


# --- client (REQ-OURA-06/07) ------------------------------------------------------------------
def test_401_refreshes_once_and_retries():
    store = MemoryStore(token())
    http = FakeHTTP(Resp(401), Resp(200, TOKEN_BODY), Resp(200, {"data": [{"id": "a"}]}))
    assert OuraClient(S, store, http, now=lambda: NOW).collection("sleep") == [{"id": "a"}]
    assert http.calls[0][2]["headers"]["Authorization"] == "Bearer acc-old"
    assert http.calls[2][2]["headers"]["Authorization"] == "Bearer acc-new"


def test_second_401_is_reported_as_no_access_and_not_refreshed_again():
    http = FakeHTTP(Resp(401), Resp(200, TOKEN_BODY), Resp(401))
    c = OuraClient(S, MemoryStore(token()), http, now=lambda: NOW)
    with pytest.raises(NoAccess, match="scope"):
        c.collection("vO2_max")
    c.http = FakeHTTP(Resp(401))                            # token already refreshed in this run: no 2nd refresh
    with pytest.raises(NoAccess):
        c.collection("daily_spo2")
    assert len(c.http.calls) == 1


def test_failed_refresh_still_asks_to_sign_in_again():
    http = FakeHTTP(Resp(401), Resp(400, {"error": "invalid_grant"}))
    with pytest.raises(auth.AuthError):
        OuraClient(S, MemoryStore(token()), http, now=lambda: NOW).collection("sleep")


def test_429_waits_retry_after_then_succeeds():
    waits = []
    http = FakeHTTP(Resp(429, headers={"Retry-After": "17"}), Resp(200, {"data": [{"id": "b"}]}))
    c = OuraClient(S, MemoryStore(token()), http, sleep=waits.append, now=lambda: NOW)
    assert c.collection("sleep") == [{"id": "b"}] and waits == [17.0]


def test_429_gives_up_after_three_waits_and_403_explains():
    http = FakeHTTP(*[Resp(429, headers={"Retry-After": "5000"})] * 4)
    waits = []
    with pytest.raises(OuraError, match="429"):
        OuraClient(S, MemoryStore(token()), http, sleep=waits.append, now=lambda: NOW).collection("sleep")
    assert waits == [900, 900, 900]                         # capped at 15 min
    with pytest.raises(OuraError, match="membership"):
        OuraClient(S, MemoryStore(token()), FakeHTTP(Resp(403)), now=lambda: NOW).collection("sleep")


def test_pagination_and_sandbox_base():
    http = FakeHTTP(Resp(200, {"data": [{"id": 1}], "next_token": "n2"}), Resp(200, {"data": [{"id": 2}]}))
    c = OuraClient(S, MemoryStore(token()), http, sandbox=True, now=lambda: NOW)
    assert c.sleep_periods("2026-11-19", "2026-11-23") == [{"id": 1}, {"id": 2}]
    assert http.calls[0][1] == f"{SANDBOX_BASE}/sleep" and http.calls[1][2]["params"]["next_token"] == "n2"
    assert OuraClient(S, MemoryStore(), FakeHTTP()).base == API_BASE
    with pytest.raises(auth.AuthError, match="login"):
        OuraClient(S, MemoryStore(), FakeHTTP()).collection("sleep")


# --- data (REQ-OURA-04/05) --------------------------------------------------------------------
NIGHT = {"id": "n1", "day": "2026-11-21", "type": "long_sleep",
         "bedtime_start": "2026-11-20T23:10:00-06:00", "bedtime_end": "2026-11-21T06:40:00-06:00",
         "time_in_bed": 27000, "total_sleep_duration": 24000, "deep_sleep_duration": 4800,
         "light_sleep_duration": 13200, "rem_sleep_duration": 6000, "awake_time": 3000, "efficiency": 89,
         "average_hrv": 48, "lowest_heart_rate": 52, "sleep_phase_30_sec": "4421", "sleep_phase_5_min": "42",
         "heart_rate": {"interval": 300, "items": [60], "timestamp": "2026-11-20T23:10:00.000-06:00"}}


def test_timestamps_converted_to_utc():
    assert to_utc("2026-11-20T23:10:00-06:00").isoformat() == "2026-11-21T05:10:00+00:00"
    assert to_utc("2026-11-21T05:10:00Z").tzinfo == timezone.utc
    with pytest.raises(ValueError, match="offset"):
        to_utc("2026-11-21T05:10:00")
    r = normalise_sleep(NIGHT)
    assert r["bedtime_start"] == "2026-11-21T05:10:00Z" and r["bedtime_end"] == "2026-11-21T12:40:00Z"
    assert r["utc_offset"] == "-06:00" and r["heart_rate"]["timestamp"] == "2026-11-21T05:10:00Z"


def test_hypnogram_and_summary():
    r = normalise_sleep(NIGHT)
    h = hypnogram(r)
    assert [s for _, s in h] == ["awake", "awake", "light", "deep"]
    assert (h[3][0] - h[0][0]).total_seconds() == 90
    assert [s for _, s in hypnogram(r, 300)] == ["awake", "light"]
    n = night_summary(r)
    assert n["start_local"] == "23:10" and n["end_local"] == "06:40"        # local clock restored
    assert n["deep_min"] == 80.0 and n["sleep_min"] == 400.0 and n["deep_pct"] == 20.0 and n["has_30s"]


def test_pull_window_repulls_three_days_and_upserts(tmp_path):
    assert window(date(2026, 11, 22), 1) == (date(2026, 11, 19), date(2026, 11, 23))   # never fewer than 3 days
    assert window(date(2026, 11, 22), 30)[0] == date(2026, 10, 23)

    class FakeClient:
        s = S                                                    # scopes: daily heartrate

        def __init__(self, nights):
            self.nights, self.hr_calls, self.asked = nights, [], []

        def collection(self, name, **p):
            self.asked.append(name)
            if name == "sleep":
                return self.nights
            if name == "heartrate":
                self.hr_calls.append((p["start_datetime"], p["end_datetime"]))
                return [{"timestamp": "2026-11-21T05:10:00+00:00", "bpm": 55, "source": "sleep"}]
            if name == "daily_resilience":
                raise NoAccess("daily_resilience: not covered")
            return [{"id": f"{name}-1", "day": "2026-11-21", "score": 80}]

    store = LocalStore(tmp_path)
    deleted = {**NIGHT, "id": "gone", "type": "deleted"}
    fc = FakeClient([NIGHT, deleted])
    r1 = pull(fc, store, today=date(2026, 11, 22), days=3)
    assert r1["sleep"] == {"new": 1, "updated": 0, "unchanged": 0}           # deleted periods skipped
    assert fc.hr_calls == [("2026-11-19T00:00:00Z", "2026-11-23T00:00:00Z")]
    assert "vO2_max" not in fc.asked and "daily_readiness" in fc.asked          # only granted scopes
    assert r1["daily_resilience"] == {"error": "no access (scope not granted)"}  # reported, not fatal
    assert r1["daily_readiness"]["new"] == 1
    r2 = pull(FakeClient([NIGHT]), store, today=date(2026, 11, 22))
    assert r2["sleep"] == {"new": 0, "updated": 0, "unchanged": 1} and r2["heartrate"]["unchanged"] == 1
    late = {**NIGHT, "deep_sleep_duration": 5400}                            # ring synced more data later
    assert pull(FakeClient([late]), store, today=date(2026, 11, 22))["sleep"]["updated"] == 1
    assert len(store.sleep()) == 1 and store.sleep()[0]["deep_sleep_duration"] == 5400


def test_wanted_follows_scopes():
    assert "vO2_max" in wanted("daily heartrate heart_health") and "vO2_max" not in wanted("daily heartrate")
    assert "heartrate" not in wanted("daily heartrate", heartrate=False)
    assert not {"personal_info", "email"} & set(wanted("daily heartrate heart_health spo2 workout session tag"))


def test_day_view_collects_everything_for_a_day(tmp_path):
    store = LocalStore(tmp_path)
    night = normalise_sleep({**NIGHT, "hrv": {"interval": 300, "items": [40, None, 50],
                                              "timestamp": "2026-11-20T23:10:00-06:00"}})
    store.upsert("sleep", {"n1": night, "nap": {**night, "id": "nap", "type": "late_nap"}})
    store.upsert("daily_readiness", {"r": {"id": "r", "day": "2026-11-21", "score": 77, "timestamp": "t"}})
    store.upsert("vO2_max", {"v": {"id": "v", "day": "2026-11-21", "vo2_max": 41}})
    store.upsert("heartrate", {"2026-11-21T06:00:00Z": {"bpm": 50}, "2026-11-22T06:00:00Z": {"bpm": 70}})
    v = day_view(store)
    assert v["day"] == "2026-11-21" and v["days"] == ["2026-11-21"]
    assert v["summary"]["deep_min"] == 80.0 and len(v["hypnogram"]) == 4
    assert v["daily_readiness"]["score"] == 77 and v["vO2_max"]["vo2_max"] == 41 and v["daily_spo2"] is None
    assert [b for _, b in v["hr_samples"]] == [50]                      # only samples inside the night
    assert [x for _, x in series(night, "hrv")] == [40.0, 50.0]          # gaps dropped
    assert day_view(LocalStore(tmp_path / "empty"))["day"] is None
