import httpx
import json
import logging
from datetime import datetime, timezone
from typing import Any

from src.config import StreamFitConfig

logger = logging.getLogger(__name__)


class StreamFitService:
    """
    StreamFit API client for CrossFit 514.

    Supports two auth methods:
    1. Pre-existing tokens (access-token + client + uid) — from web session
    2. Email + PIN — Devise token auth (mobile app API)

    Key endpoints discovered:
      POST /api/v1/new/auth/sign_in         — PIN auth
      GET  /api/v1/channels/{id}            — gym info
      GET  /api/v1/channels/{id}/calendar_workouts — class schedule
      GET  /api/v1/workouts/{id}            — workout details
    """

    def __init__(self, config: StreamFitConfig):
        self.config = config
        self._client = httpx.Client(timeout=30.0)

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> dict[str, Any]:
        """Authenticate via email+PIN or validate existing tokens."""
        if self.config.is_fully_authenticated():
            # Validate tokens first
            validated = self._validate_tokens()
            if validated.get("status") == "valid":
                self.config.is_authenticated = True
                return {"status": "authenticated", "method": "token"}

        # Fall back to email+PIN
        return self._authenticate_pin()

    def _validate_tokens(self) -> dict[str, Any]:
        """Check if stored tokens are still valid."""
        try:
            r = self._client.get(
                f"{self.config.base_url}/api/v1/auth/validate_token",
                headers=self._auth_headers(),
                timeout=10,
            )
            if r.status_code == 200:
                return {"status": "valid", "data": r.json()}
            return {"status": "invalid", "code": r.status_code}
        except Exception as e:
            return {"status": "error", "message": str(e)}

    def _authenticate_pin(self) -> dict[str, Any]:
        """Authenticate with email + PIN via the mobile app API."""
        if not self.config.email or not self.config.pin:
            return {"status": "error", "message": "Missing STREAMFIT_EMAIL or STREAMFIT_PIN"}

        url = f"{self.config.base_url}/api/v1/new/auth/sign_in"
        payload = {
            "input": "email",
            "phone": None,
            "email": self.config.email,
            "is_new_user": False,
            "pin": True,
            "exists_email": True,
            "code": self.config.pin,
        }
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json",
            "origin": "https://go.streamfit.com",
            "referer": "https://go.streamfit.com/",
        }

        try:
            response = self._client.post(url, json=payload, headers=headers)
            response.raise_for_status()
        except httpx.HTTPStatusError as e:
            return {"status": "error", "message": f"Auth failed ({e.response.status_code}): {e.response.text[:200]}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

        headers_map = dict(response.headers)
        self.config.access_token = headers_map.get("access-token", "")
        self.config.client = headers_map.get("client", "")
        self.config.expiry = headers_map.get("expiry", "")
        self.config.uid = headers_map.get("uid", "")

        if not self.config.access_token:
            return {"status": "error", "message": "No access-token in response headers"}

        self.config.is_authenticated = True
        return {"status": "authenticated", "method": "pin"}

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "access-token": self.config.access_token or "",
            "client": self.config.client or "",
            "expiry": self.config.expiry or "",
            "uid": self.config.uid or "",
        }

    def _ensure_auth(self) -> dict[str, Any]:
        if not self.config.is_authenticated:
            return self.authenticate()
        return {"status": "ok"}

    # ── Channel / Gym ──────────────────────────────────────────────────────────

    def get_gym_info(self) -> str:
        """Get CrossFit 514 gym information."""
        auth = self._ensure_auth()
        if auth.get("status") == "error":
            return json.dumps({"error": auth["message"]})

        r = self._client.get(
            f"{self.config.base_url}/api/v1/channels/{self.config.channel_id}",
            headers=self._auth_headers(),
        )
        try:
            r.raise_for_status()
            return json.dumps(r.json(), indent=2)
        except httpx.HTTPStatusError:
            return json.dumps({"error": f"HTTP {r.status_code}"})

    # ── Schedule ───────────────────────────────────────────────────────────────

    def get_class_schedule(
        self,
        start_date: str | None = None,
        days: int = 7,
    ) -> str:
        """
        Fetch the class calendar for a date range.

        Args:
            start_date: ISO date string (YYYY-MM-DD), defaults to today
            days: number of days to fetch (default 7, max ~30)

        Returns:
            JSON array of class objects with id, name, time, type, capacity info.
        """
        auth = self._ensure_auth()
        if auth.get("status") == "error":
            return json.dumps({"error": auth["message"]})

        from datetime import datetime, timedelta
        if start_date:
            start = datetime.strptime(start_date, "%Y-%m-%d")
        else:
            start = datetime.now(timezone.utc)

        # API expects UTC timestamps
        start_utc = start.replace(hour=4, minute=0, second=0, microsecond=0)  # ~midnight EST
        end_utc = start_utc + timedelta(days=days)

        params = {
            "channel_id": self.config.channel_id,
            "start_at": start_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "end_at": end_utc.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "location_id": "",
            "timezone": "America/New_York",
        }

        r = self._client.get(
            f"{self.config.base_url}/api/v1/channels/{self.config.channel_id}/calendar_workouts",
            params=params,
            headers=self._auth_headers(),
        )
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError:
            return json.dumps({"error": f"HTTP {r.status_code}"})

        data = r.json()
        workouts = data.get("data", [])
        simplified = [
            {
                "id": w["id"],
                "name": w["name"],
                "datetime": w["scheduled_at"],
                "class_type": w.get("class_type_name", ""),
                "duration_minutes": w.get("duration_minutes"),
                "in_person_max": w.get("in_person_max_users"),
                "registered_count": w.get("registered_count"),
                "canceled": w.get("canceled", False),
                "spots_left": (
                    w.get("in_person_max_users", 0) - w.get("registered_count", 0)
                    if w.get("in_person_max_users") else None
                ),
            }
            for w in workouts
        ]
        return json.dumps({
            "status": "ok",
            "gym": "CrossFit 514",
            "channel_id": self.config.channel_id,
            "from": params["start_at"],
            "to": params["end_at"],
            "count": len(simplified),
            "classes": simplified,
        }, indent=2, ensure_ascii=False)

    # ── Workout Details ────────────────────────────────────────────────────────

    def get_workout(self, workout_id: str) -> str:
        """
        Fetch full workout details (sections, exercises, coach notes).

        Args:
            workout_id: StreamFit workout ID (integer or string)
        """
        auth = self._ensure_auth()
        if auth.get("status") == "error":
            return json.dumps({"error": auth["message"]})

        r = self._client.get(
            f"{self.config.base_url}/api/v1/workouts/{workout_id}",
            headers=self._auth_headers(),
        )
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            return json.dumps({"error": f"HTTP {e.response.status_code}: {e.response.text[:200]}"})

        return r.text

    def get_coach_notes(self, workout_id: str) -> str:
        """Extract coach notes from a workout's sections."""
        import json
        raw = self.get_workout(workout_id)
        try:
            root = json.loads(raw)
        except json.JSONDecodeError:
            return f"Error: could not parse response as JSON: {raw[:200]}"

        notes = []
        try:
            sections = root.get("data", {}).get("sections", [])
            for section in sections:
                note = section.get("coach_notes")
                if note and isinstance(note, str) and note.strip():
                    notes.append(note.strip())
        except Exception as e:
            return f"Error extracting coach notes: {str(e)}"

        if not notes:
            return "No coach notes found for this workout."
        return "\n\n".join(notes)
