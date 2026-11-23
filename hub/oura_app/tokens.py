"""Token storage (REQ-OURA-03).

On the laptop, tokens live in Windows Credential Manager through `keyring`; Windows encrypts them
at rest (DPAPI) for this Windows user only. The hub in Docker (task 5b) will need an encrypted
file instead; anything with load/save/delete fits.
"""
import json
from dataclasses import asdict, dataclass, field

from .config import KEYRING_SERVICE

DEFAULT_EXPIRES_IN_S = 3600     # if Oura's token response has no expires_in, assume 1 h (refreshes early, never late)


@dataclass
class Token:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float               # Unix seconds (UTC)
    token_type: str = "bearer"

    @classmethod
    def from_response(cls, body: dict, now: float) -> "Token":
        return cls(body["access_token"], body["refresh_token"], now + float(body.get("expires_in") or DEFAULT_EXPIRES_IN_S),
                   body.get("token_type", "bearer"))


class MemoryStore:
    def __init__(self, token: Token | None = None):
        self.token = token

    def load(self):
        return self.token

    def save(self, token: Token):
        self.token = token

    def delete(self):
        self.token = None


class KeyringStore:
    """One credential entry: service 'tinyml-oura', user 'oura-tokens', value = JSON."""

    def __init__(self, service: str = KEYRING_SERVICE, user: str = "oura-tokens", backend=None):
        if backend is None:
            import keyring as backend
        self.kr, self.service, self.user = backend, service, user

    def load(self):
        raw = self.kr.get_password(self.service, self.user)
        return Token(**json.loads(raw)) if raw else None

    def save(self, token: Token):
        self.kr.set_password(self.service, self.user, json.dumps(asdict(token)))

    def delete(self):
        if self.kr.get_password(self.service, self.user) is not None:
            self.kr.delete_password(self.service, self.user)


class TokenLock:
    """Cross-process lock around refresh + save (refresh tokens are single-use).

    The scheduled pull and a manual run (e.g. the demo screen) can refresh at the same moment; without
    a lock the second refresh spends a token the first has already used, and Oura answers invalid_grant.
    A lock file created with O_EXCL works on Windows and Linux; one older than `stale_s` is taken over
    (its process died)."""

    def __init__(self, path, timeout_s: float = 30.0, stale_s: float = 120.0, sleep=None, clock=None):
        import time as _t
        from pathlib import Path
        self.path, self.timeout_s, self.stale_s = Path(path), timeout_s, stale_s
        self.sleep, self.clock = sleep or _t.sleep, clock or _t.time

    def __enter__(self):
        import os
        self.path.parent.mkdir(parents=True, exist_ok=True)
        deadline = self.clock() + self.timeout_s
        while True:
            try:
                fd = os.open(self.path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return self
            except FileExistsError:
                try:
                    if self.clock() - self.path.stat().st_mtime > self.stale_s:
                        self.path.unlink(missing_ok=True)
                        continue
                except FileNotFoundError:
                    continue
                if self.clock() > deadline:
                    raise TimeoutError(f"another Oura run holds {self.path.name}; try again in a minute")
                self.sleep(0.2)

    def __exit__(self, *exc):
        self.path.unlink(missing_ok=True)
        return False
