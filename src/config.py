import os
from dataclasses import dataclass, field
from dotenv import load_dotenv

load_dotenv()


@dataclass
class StreamFitConfig:
    base_url: str = os.getenv("STREAMFIT_BASE_URL", "https://api.streamfit.com")
    email: str = os.getenv("STREAMFIT_EMAIL", "")
    pin: str = os.getenv("STREAMFIT_PIN", "")
    channel_id: str = os.getenv("STREAMFIT_CHANNEL_ID", "812")

    # Pre-existing auth tokens (from web session)
    access_token: str = os.getenv("STREAMFIT_ACCESS_TOKEN", "")
    client: str = os.getenv("STREAMFIT_CLIENT", "")
    expiry: str = os.getenv("STREAMFIT_EXPIRY", "")
    uid: str = os.getenv("STREAMFIT_UID", "")

    # Internal state
    is_authenticated: bool = False

    def is_fully_authenticated(self) -> bool:
        return bool(self.access_token and self.client and self.uid)
