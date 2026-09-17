import httpx
import json
import logging
from datetime import datetime, timedelta, timezone
from typing import Any

from src.config import StreamFitConfig

logger = logging.getLogger(__name__)


class StreamFitService:
    """
    StreamFit API client for CrossFit 514.

    Auth (2026 — current API):
      The old /api/v1/new/auth/sign_in PIN flow is DEAD ("Update your app").
      The web app now uses: reCAPTCHA v3 -> federate -> verify_pin -> verify_mfa
      (email code). Google scores programmatic captcha tokens too low, so
      headless-token auth fails with 403 "Recaptcha verification failed".

      Working strategy (implemented here):
        1. Try saved Devise tokens (access-token/client/uid — long-lived).
        2. If invalid, run the real login UI in headless Chromium
           (src/browser_login.py) — passes reCAPTCHA because it IS a real
           browser session. MFA code is read from Gmail via gws CLI.
        3. Save tokens for fast reuse.

    Key endpoints (verified working):
      GET  /api/v1/auth/validate_token              — token check
      GET  /api/v1/channels/{id}                    — gym info
      GET  /api/v1/channels/{id}/calendar_workouts  — full class schedule
      GET  /api/v1/users/calendar/workouts_by_day   — MY calendar (has
                                                      `registered` flag)
      GET  /api/v1/workouts/{id}                    — workout details
    """

    def __init__(self, config: StreamFitConfig):
        self.config = config
        self._client = httpx.Client(timeout=30.0)
        self._user_id: int | None = None

    @property
    def user_id(self) -> int | None:
        """Numeric StreamFit user id (needed by register_status). Resolved once
        from validate_token — ensures tokens are loaded/auth'd first."""
        if self._user_id is not None:
            return self._user_id
        # make sure tokens are loaded BEFORE hitting validate_token
        self.config.load_tokens_from_file()
        try:
            r = self._client.get(
                f"{self.config.base_url}/api/v1/auth/validate_token",
                headers=self._auth_headers(),
                timeout=10,
            )
            if r.status_code == 200:
                data = r.json().get("data", {})
                self._user_id = data.get("id")
        except Exception:
            self._user_id = None
        return self._user_id

    # ── Auth ──────────────────────────────────────────────────────────────────

    def authenticate(self) -> dict[str, Any]:
        """Validate saved tokens; on failure, re-login via headless browser."""
        # env tokens take priority; otherwise load from tokens file
        self.config.load_tokens_from_file()

        if self.config.is_fully_authenticated():
            validated = self._validate_tokens()
            if validated.get("status") == "valid":
                self.config.is_authenticated = True
                return {"status": "authenticated", "method": "token"}

        from src.browser_login import BrowserLogin
        login = BrowserLogin(
            email=self.config.email,
            pin=self.config.pin,
            tokens_path=self.config.tokens_path,
        )
        result = login.login()
        if result.get("status") == "authenticated":
            # reload freshly saved tokens into config
            self.config.access_token = ""
            self.config.load_tokens_from_file()
            self.config.is_authenticated = True
        return result

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

    def _auth_headers(self) -> dict[str, str]:
        return {
            "Accept": "application/json",
            "access-token": self.config.access_token or "",
            "client": self.config.client or "",
            "expiry": self.config.expiry or "",
            "uid": self.config.uid or "",
        }

    def _ensure_auth(self) -> dict[str, Any]:
        if self.config.is_authenticated:
            return {"status": "ok"}
        return self.authenticate()

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

        start = self._parse_start(start_date)
        params = {
            "start_at": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "end_at": (start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "timezone": self.config.timezone,
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
                "registered_count": w.get("count_in_person_users", w.get("registered_count")),
                "canceled": w.get("canceled", False),
                "coach": (w.get("main_coach") or {}).get("name"),
                "spots_left": (
                    w.get("in_person_max_users", 0) - w.get("count_in_person_users", 0)
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

    # ── My registrations ──────────────────────────────────────────────────────

    def get_my_registrations(self, start_date: str | None = None, days: int = 14) -> str:
        """
        List MY booked classes (registered=true) and waitlist entries.

        Uses /users/calendar/workouts_by_day — the endpoint the web dashboard
        uses, which carries the per-user `registered` flag.
        """
        auth = self._ensure_auth()
        if auth.get("status") == "error":
            return json.dumps({"error": auth["message"]})

        start = self._parse_start(start_date) - timedelta(days=1)
        params = {
            "start_at": start.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "end_at": (start + timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "timezone": self.config.timezone,
        }

        r = self._client.get(
            f"{self.config.base_url}/api/v1/users/calendar/workouts_by_day",
            params=params,
            headers=self._auth_headers(),
        )
        try:
            r.raise_for_status()
        except httpx.HTTPStatusError as e:
            return json.dumps({"error": f"HTTP {r.status_code}: {e.response.text[:200]}"})

        data = r.json()
        booked, waitlisted = [], []
        for day in data.get("workouts", []):
            for w in day.get("data", []):
                wd = w.get("workoutData", {})
                entry = {
                    "id": wd.get("id"),
                    "name": wd.get("name"),
                    "datetime": wd.get("scheduled_at"),
                    "coach": (wd.get("main_coach") or {}).get("name"),
                    "canceled": wd.get("canceled", False),
                    "spots": f"{wd.get('count_in_person_users')}/{wd.get('in_person_max_users')}",
                }
                if wd.get("registered"):
                    booked.append(entry)
                elif (wd.get("waitlist_count") or 0) > 0:
                    entry["waitlist_position"] = wd.get("waitlist_count")
                    waitlisted.append(entry)

        return json.dumps({
            "status": "ok",
            "gym": "CrossFit 514",
            "booked_count": len(booked),
            "booked": booked,
            "waitlisted": waitlisted,
        }, indent=2, ensure_ascii=False)

    # ── Register / Cancel (athlete flow, REVERSE-ENGINEERED 2026-09-17) ────────
    #
    # The bundle shows the athlete UI uses:
    #   POST /workouts/{id}/purchase  {workoutId, type, channelKeyId, directCheckin}
    #      -> 200 {}     (registers; this is the same call the "Register" button makes)
    #   POST /workouts/{id}/refund    {childId: null}
    #      -> 200 {}     (cancels / refunds the registration)
    # The old admin-ish endpoints (/channel_members/.../register, /workouts_users/
    # .../inactivate_user) are NOT usable from the athlete session.

    def _get_channel_key_id(self, workout_id: str) -> int | None:
        """Return the first active membership channel key for a workout (for the
        `channelKeyId` field of the register call)."""
        try:
            r = self._client.get(
                f"{self.config.base_url}/api/v1/workouts_users/{workout_id}/register_status/{self.user_id}",
                headers=self._auth_headers(),
            )
            r.raise_for_status()
            keys = r.json().get("channel_keys", [])
            for k in keys:
                if k.get("active"):
                    return k.get("id")
        except Exception:
            return None
        return None

    def register_class(self, workout_id: str, channel_key_id: int | None = None,
                       class_type: str = "inPerson", direct_checkin: bool = False) -> str:
        """
        Register ME for a class (athlete flow).

        Args:
            workout_id: StreamFit workout ID (integer or string)
            channel_key_id: membership key id (auto-detected if omitted)
            class_type: "inPerson" or "online"
            direct_checkin: True to check in directly

        Returns:
            JSON with status + registration confirmation.
        """
        auth = self._ensure_auth()
        if auth.get("status") == "error":
            return json.dumps({"error": auth["message"]})

        if channel_key_id is None:
            channel_key_id = self._get_channel_key_id(workout_id)
        if channel_key_id is None:
            return json.dumps({"error": "No active membership channel key found"})

        body = {
            "workoutId": int(workout_id),
            "type": class_type,
            "channelKeyId": channel_key_id,
            "directCheckin": direct_checkin,
        }
        r = self._client.post(
            f"{self.config.base_url}/api/v1/workouts/{workout_id}/purchase",
            json=body,
            headers=self._auth_headers(),
        )
        try:
            r.raise_for_status()
            return json.dumps({"status": "ok", "registered": True,
                               "workout_id": int(workout_id),
                               "channel_key_id": channel_key_id,
                               "type": class_type}, indent=2)
        except httpx.HTTPStatusError as e:
            return json.dumps({"status": "error",
                               "error": f"HTTP {e.response.status_code}",
                               "detail": e.response.text[:300]})

    def cancel_registration(self, workout_id: str) -> str:
        """
        Cancel MY registration for a class (athlete flow).

        Args:
            workout_id: StreamFit workout ID (integer or string)

        Returns:
            JSON with status + cancellation confirmation.
        """
        auth = self._ensure_auth()
        if auth.get("status") == "error":
            return json.dumps({"error": auth["message"]})

        r = self._client.post(
            f"{self.config.base_url}/api/v1/workouts/{workout_id}/refund",
            json={"childId": None},
            headers=self._auth_headers(),
        )
        try:
            r.raise_for_status()
            return json.dumps({"status": "ok", "registered": False,
                               "workout_id": int(workout_id)}, indent=2)
        except httpx.HTTPStatusError as e:
            return json.dumps({"status": "error",
                               "error": f"HTTP {e.response.status_code}",
                               "detail": e.response.text[:300]})

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

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _parse_start(self, start_date: str | None) -> datetime:
        if start_date:
            return datetime.strptime(start_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc).replace(hour=4, minute=0, second=0, microsecond=0)
