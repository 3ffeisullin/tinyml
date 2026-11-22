"""OAuth2 authorization-code sign-in with PKCE and a localhost callback (REQ-OURA-01/02/03).

Flow: open Oura's consent page in the browser -> the user clicks Allow -> Oura redirects the
browser to http://localhost:8080/callback?code=...&state=... -> a one-shot local web server
catches it -> the code is exchanged for tokens, which go to the token store.
Refresh tokens are single-use: every refresh returns a new one, saved at once.
"""
import base64
import hashlib
import secrets
import threading
import time
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import parse_qs, urlencode, urlparse

from .config import AUTHORIZE_URL, TOKEN_URL, USER_AGENT, Settings
from .tokens import Token


class AuthError(RuntimeError):
    pass


def pkce_pair() -> tuple[str, str]:
    verifier = secrets.token_urlsafe(64)[:96]
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    return verifier, challenge


def authorize_url(s: Settings, state: str, challenge: str) -> str:
    q = {"response_type": "code", "client_id": s.client_id, "redirect_uri": s.redirect_uri, "scope": s.scopes,
         "state": state, "code_challenge": challenge, "code_challenge_method": "S256"}
    return f"{AUTHORIZE_URL}?{urlencode(q)}"


def parse_callback(path: str, expected_state: str) -> str:
    """Query of the redirect -> authorization code. Raises AuthError on denial or a state mismatch (CSRF)."""
    q = {k: v[0] for k, v in parse_qs(urlparse(path).query).items()}
    if q.get("state") != expected_state:
        raise AuthError("state mismatch on the callback; sign-in aborted")
    if "error" in q:
        raise AuthError(f"Oura returned error: {q['error']}")
    if not q.get("code"):
        raise AuthError("callback without a code")
    return q["code"]


def _token_request(http, s: Settings, form: dict, now: float) -> Token:
    r = http.post(TOKEN_URL, data={**form, "client_id": s.client_id, "client_secret": s.client_secret},
                  headers={"User-Agent": USER_AGENT}, timeout=30)
    if r.status_code != 200:
        # The body may echo request details; show only the status and Oura's error code.
        try:
            err = r.json().get("error", "")
        except ValueError:
            err = ""
        raise AuthError(f"token request failed: HTTP {r.status_code} {err}".strip())
    return Token.from_response(r.json(), now)


def exchange_code(http, s: Settings, code: str, verifier: str, now: float | None = None) -> Token:
    return _token_request(http, s, {"grant_type": "authorization_code", "code": code,
                                    "redirect_uri": s.redirect_uri, "code_verifier": verifier},
                          time.time() if now is None else now)


def refresh(http, s: Settings, token: Token, store, now: float | None = None) -> Token:
    new = _token_request(http, s, {"grant_type": "refresh_token", "refresh_token": token.refresh_token},
                         time.time() if now is None else now)
    store.save(new)          # the old refresh token is now invalid
    return new


PAGE = """<!doctype html><meta charset="utf-8"><title>TinyML EEG - Oura</title>
<body style="font-family:system-ui;max-width:34em;margin:4em auto;line-height:1.5">
<h2>{title}</h2><p>{text}</p></body>"""


def wait_for_callback(s: Settings, state: str, timeout: float = 300) -> str:
    """Serve one request on the redirect URI's host/port; return the code."""
    u = urlparse(s.redirect_uri)
    result: dict = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if urlparse(self.path).path != u.path:
                self.send_response(404); self.end_headers(); return
            try:
                result["code"] = parse_callback(self.path, state)
                title, text = "Connected to Oura", "Sign-in worked. You can close this tab and go back to the terminal."
            except AuthError as e:
                result["error"] = str(e)
                title, text = "Sign-in failed", str(e)
            body = PAGE.format(title=title, text=text).encode()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(body))); self.end_headers(); self.wfile.write(body)

        def log_message(self, *a):  # keep the code out of the console
            pass

    srv = HTTPServer((u.hostname, u.port or 80), Handler)
    srv.timeout = 1
    deadline = time.time() + timeout
    try:
        while "code" not in result and "error" not in result and time.time() < deadline:
            srv.handle_request()
    finally:
        srv.server_close()
    if "error" in result:
        raise AuthError(result["error"])
    if "code" not in result:
        raise AuthError(f"no callback within {timeout:.0f} s")
    return result["code"]


def login(http, s: Settings, store, open_browser: bool = True, timeout: float = 300) -> Token:
    state = secrets.token_urlsafe(24)
    verifier, challenge = pkce_pair()
    url = authorize_url(s, state, challenge)
    print("Opening Oura's sign-in page in your browser. Log in and click Allow.")
    print("If no browser opens, paste this URL into one:\n  " + url, flush=True)
    if open_browser:
        threading.Timer(0.5, webbrowser.open, (url,)).start()
    code = wait_for_callback(s, state, timeout)
    token = exchange_code(http, s, code, verifier)
    store.save(token)
    return token
