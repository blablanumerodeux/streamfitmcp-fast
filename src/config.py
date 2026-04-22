import os
import time
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class StreamFitConfig:
    base_url: str = os.getenv("STREAMFIT_BASE_URL", "https://api.streamfit.com")
    email: str = os.getenv("STREAMFIT_EMAIL", "")
    pin: str = os.getenv("STREAMFIT_PIN", "")

    # Pre-set tokens from environment (e.g. extracted from browser session)
    auth_token: str | None = os.getenv("STREAMFIT_ACCESS_TOKEN") or None
    client: str | None = os.getenv("STREAMFIT_CLIENT") or None
    expiry: str | None = os.getenv("STREAMFIT_EXPIRY") or None
    uid: str | None = os.getenv("STREAMFIT_UID") or None

    def is_authenticated(self) -> bool:
        if not all([self.auth_token, self.client, self.expiry, self.uid]):
            return False
        try:
            return (int(self.expiry) * 1000) > int(time.time() * 1000)
        except (ValueError, TypeError):
            return False

    def clear_auth(self):
        self.auth_token = None
        self.client = None
        self.expiry = None
        self.uid = None
