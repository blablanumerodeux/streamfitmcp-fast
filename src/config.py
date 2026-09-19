import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

DEFAULT_TOKENS_PATH = str(
    Path(__file__).resolve().parent.parent / ".tokens.json"
)


@dataclass
class StreamFitConfig:
    base_url: str = os.getenv("STREAMFIT_BASE_URL", "https://api.streamfit.com")
    email: str = os.getenv("STREAMFIT_EMAIL", "")
    pin: str = os.getenv("STREAMFIT_PIN", "")
    channel_id: str = os.getenv("STREAMFIT_CHANNEL_ID", "812")
    timezone: str = os.getenv("STREAMFIT_TZ", "America/New_York")

    # Where the browser-login flow persists Devise tokens (gitignored)
    tokens_path: str = os.getenv(
        "STREAMFIT_TOKENS_PATH",
        DEFAULT_TOKENS_PATH,
    )

    # Pre-existing auth tokens (from web session) — env overrides file
    access_token: str = os.getenv("STREAMFIT_ACCESS_TOKEN", "")
    client: str = os.getenv("STREAMFIT_CLIENT", "")
    expiry: str = os.getenv("STREAMFIT_EXPIRY", "")
    uid: str = os.getenv("STREAMFIT_UID", "")

    # Internal state
    is_authenticated: bool = False

    # Auth error bookkeeping (not persisted)
    last_auth_error: str = field(default="", repr=False)

    def is_fully_authenticated(self) -> bool:
        return bool(self.access_token and self.client and self.uid)

    def load_tokens_from_file(self) -> bool:
        """Load Devise tokens from the tokens file (if env vars not set)."""
        if self.is_fully_authenticated():
            return True
        try:
            path = Path(self.tokens_path)
            if not path.exists():
                self.last_auth_error = f"Tokens file not found: {self.tokens_path}"
                return False
            with path.open() as f:
                tok = json.load(f)
            self.access_token = tok.get("access-token") or tok.get("access_token") or ""
            self.client = tok.get("client", "")
            self.uid = tok.get("uid", "")
            self.expiry = str(tok.get("expiry", ""))
            self.email = self.email or tok.get("email", "")
            if not self.is_fully_authenticated():
                self.last_auth_error = "Tokens file missing access-token/client/uid"
                return False
            self.last_auth_error = ""
            return True
        except json.JSONDecodeError as exc:
            self.last_auth_error = f"Tokens file JSON decode error: {exc}"
            return False
        except OSError as exc:
            self.last_auth_error = f"Tokens file read error: {exc}"
            return False

    def save_tokens(self, tokens: dict[str, str]) -> bool:
        """Persist Devise tokens to the tokens file."""
        try:
            path = Path(self.tokens_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            payload = dict(tokens)
            if "email" not in payload:
                payload["email"] = self.email
            with path.open("w") as f:
                json.dump(payload, f, indent=2)
            # Update in-memory state too
            self.access_token = payload.get("access-token") or payload.get("access_token", "")
            self.client = payload.get("client", "")
            self.uid = payload.get("uid", "")
            self.expiry = str(payload.get("expiry", ""))
            self.last_auth_error = ""
            return True
        except OSError as exc:
            self.last_auth_error = f"Failed to save tokens: {exc}"
            return False
