import time
from typing import Any

import httpx

from src.config import StreamFitConfig


class StreamFitService:
    def __init__(self, config: StreamFitConfig):
        self.config = config
        self._client = httpx.Client(timeout=30.0)

    def authenticate(self) -> dict[str, Any]:
        """Authenticate with StreamFit API using email + PIN (Devise token auth)."""
        if self.config.is_authenticated():
            return {"status": "already_authenticated"}

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
            return {"status": "error", "message": f"Auth failed ({e.response.status_code}): {e.response.text}"}
        except Exception as e:
            return {"status": "error", "message": str(e)}

        # Extract auth tokens from response headers (Devise token auth)
        headers_map = dict(response.headers)
        self.config.auth_token = headers_map.get("access-token")
        self.config.client = headers_map.get("client")
        self.config.expiry = headers_map.get("expiry")
        self.config.uid = headers_map.get("uid")

        if not self.config.auth_token:
            return {"status": "error", "message": "No access-token in response headers"}

        return {"status": "authenticated"}

    def _auth_headers(self) -> dict[str, str]:
        """Return headers required for authenticated requests."""
        self.authenticate()  # Ensure valid token
        return {
            "Accept": "application/json",
            "access-token": self.config.auth_token or "",
            "client": self.config.client or "",
            "expiry": self.config.expiry or "",
            "uid": self.config.uid or "",
        }

    def get_workout(self, workout_id: str) -> str:
        """Fetch raw workout data by ID."""
        auth_result = self.authenticate()
        if auth_result.get("status") == "error":
            return f'{{"error": "{auth_result["message"]}"}}'

        url = f"{self.config.base_url}/api/v1/workouts/{workout_id}"
        try:
            response = self._client.get(url, headers=self._auth_headers())
            response.raise_for_status()
            return response.text
        except httpx.HTTPStatusError as e:
            return f'{{"error": "HTTP {e.response.status_code}: {e.response.text}"}}'
        except Exception as e:
            return f'{{"error": "{str(e)}"}}'

    def get_coach_notes(self, workout_id: str) -> str:
        """Extract coach notes from a workout's sections."""
        import json

        workout_json = self.get_workout(workout_id)
        try:
            root = json.loads(workout_json)
        except json.JSONDecodeError:
            return f"Error: could not parse response as JSON: {workout_json[:200]}"

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
