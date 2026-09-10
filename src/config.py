import json
import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class StreamFitConfig:
    base_url: str = os.getenv("STREAMFIT_BASE_URL", "https://api.streamfit.com")
    email: str = os.getenv("STREAMFIT_EMAIL", "")
    pin: str = os.getenv("STREAMFIT_PIN", "")
    channel_id: str = os.getenv("STREAMFIT_CHANNEL_ID", "812")
    timezone: str = os.getenv("STREAMFIT_TZ", "America/New_York")

    # Where the browser-login flow persists Devise tokens (gitignored)
    tokens_path: str = os.getenv("STREAMFIT_TOKENS_PATH", os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".tokens.json"))

    # Pre-existing auth tokens (from web session) — env overrides file
    access_token: str = os.getenv("STREAMFIT_ACCESS_TOKEN", "")
    client: str = os.getenv("STREAMFIT_CLIENT", "")
    expiry: str = os.getenv("STREAMFIT_EXPIRY", "")
    uid: str = os.getenv("STREAMFIT_UID", "")

    # Internal state
    is_authenticated: bool = False

    def is_fully_authenticated(self) -> bool:
        return bool(self.access_token and self.client and self.uid)

    def load_tokens_from_file(self) -> bool:
        """Load Devise tokens from the tokens file (if env vars not set)."""
        if self.is_fully_authenticated():
            return True
        try:
            with open(self.tokens_path) as f:
                tok = json.load(f)
            self.access_token = tok.get("access-token") or tok.get("access_token") or ""
            self.client = tok.get("client", "")
            self.uid = tok.get("uid", "")
            self.expiry = str(tok.get("expiry", ""))
            self.email = self.email or tok.get("email", "")
            return self.is_fully_authenticated()
        except (FileNotFoundError, json.JSONDecodeError):
            return False
