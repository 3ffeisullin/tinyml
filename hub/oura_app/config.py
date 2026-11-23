"""Settings from the git-ignored .env file (REQ-OURA-01/02). Secrets are never printed."""
from dataclasses import dataclass, field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ENV_FILE = ROOT / ".env"
DATA_DIR = ROOT / "data" / "oura"

AUTHORIZE_URL = "https://cloud.ouraring.com/oauth/authorize"
TOKEN_URL = "https://api.ouraring.com/oauth/token"
REVOKE_URL = "https://api.ouraring.com/oauth/revoke"
API_BASE = "https://api.ouraring.com/v2/usercollection"
SANDBOX_BASE = "https://api.ouraring.com/v2/sandbox/usercollection"
USER_AGENT = "tinyml-eeg-hub/0.1"          # Oura requires a non-empty User-Agent
KEYRING_SERVICE = "tinyml-oura"

REPULL_DAYS = 3                 # REQ-OURA-04: re-pull the last 3 days to catch late ring syncs
REFRESH_MARGIN_S = 300          # refresh the access token when it has less than 5 min left
MAX_RETRY_AFTER_S = 900         # never wait longer than 15 min on a 429
MAX_429_RETRIES = 3

# Every Oura collection the app knows, with the OAuth scope it needs and how it is queried
# ("date" = start_date/end_date, "datetime" = start_datetime/end_datetime). `pull` fetches the ones
# whose scope is in OURA_SCOPES; a collection the sign-in doesn't cover is reported, not fatal.
# Email and personal info are deliberately absent (privacy; not needed).
COLLECTIONS = {
    "sleep": ("daily", "date"),                     # sleep periods: hypnograms, HR/HRV series, durations
    "daily_sleep": ("daily", "date"),               # sleep score + contributors
    "daily_readiness": ("daily", "date"),           # readiness score, temperature deviation
    "daily_activity": ("daily", "date"),            # activity score, steps, calories, MET
    "daily_stress": ("daily", "date"),              # stress / recovery minutes
    "daily_resilience": ("daily", "date"),          # resilience level
    "sleep_time": ("daily", "date"),                # recommended bedtime
    "rest_mode_period": ("daily", "date"),
    "daily_cardiovascular_age": ("heart_health", "date"),
    "vO2_max": ("heart_health", "date"),
    "daily_spo2": ("spo2", "date"),
    "workout": ("workout", "date"),
    "session": ("session", "date"),
    "tag": ("tag", "date"),
    "enhanced_tag": ("tag", "date"),
    "heartrate": ("heartrate", "datetime"),         # 5-min (day) / per-beat-window (sleep) samples
}


class ConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class Settings:
    client_id: str
    client_secret: str = field(repr=False)
    redirect_uri: str = "http://localhost:8080/callback"
    scopes: str = "daily heartrate heart_health"

    def __repr__(self):  # never show the secret, even in tracebacks
        return f"Settings(client_id={self.client_id[:4]}…, redirect_uri={self.redirect_uri!r}, scopes={self.scopes!r})"


def parse_env(text: str) -> dict:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        out[k.strip()] = v.strip().strip('"').strip("'")
    return out


def load_settings(path: Path = ENV_FILE) -> Settings:
    if not path.exists():
        raise ConfigError(f"{path} not found. Copy .env.example to .env and fill in the Oura client ID and secret.")
    env = parse_env(path.read_text(encoding="utf-8-sig"))
    missing = [k for k in ("OURA_CLIENT_ID", "OURA_CLIENT_SECRET") if not env.get(k)]
    if missing:
        raise ConfigError(f"{path.name} is missing values for: {', '.join(missing)}")
    return Settings(env["OURA_CLIENT_ID"], env["OURA_CLIENT_SECRET"],
                    env.get("OURA_REDIRECT_URI") or Settings.redirect_uri,
                    env.get("OURA_SCOPES") or Settings.scopes)
