"""Token storage (REQ-OURA-03).

On the laptop, tokens live in Windows Credential Manager through `keyring`; Windows encrypts them
at rest (DPAPI) for this Windows user only. The hub in Docker (task 5b) will need an encrypted
file instead; anything with load/save/delete fits.
"""
import json
from dataclasses import asdict, dataclass, field

from .config import KEYRING_SERVICE


@dataclass
class Token:
    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: float               # Unix seconds (UTC)
    token_type: str = "bearer"

    @classmethod
    def from_response(cls, body: dict, now: float) -> "Token":
        return cls(body["access_token"], body["refresh_token"], now + float(body.get("expires_in", 0)),
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
