#!/usr/bin/env python3
"""StreamFit MCP Server — FastMCP implementation.

Wraps the StreamFit API (CrossFit 514, channel 812) as MCP tools:
  - get_gym_info()            — gym/channel info
  - get_class_schedule()      — upcoming class calendar
  - get_my_registrations()    — MY booked classes + waitlist
  - register_class()          — register (athlete "purchase" flow)
  - cancel_registration()     — cancel  (athlete "refund" flow)
  - get_workout()             — full workout details by ID
  - get_coach_notes()         — coach notes extracted from a workout
  - get_auth_status()         — token/health check (no side effects)

Auth: saved Devise tokens in .tokens.json; falls back to a real headless
Chromium login (MFA code read from Gmail) when they expire.

Run:
    /root/.hermes/hermes-agent/venv/bin/python main.py     # stdio transport

IMPORTANT: never print to stdout — it is the MCP protocol channel. Logging is
sent to stderr (LOG_LEVEL, default WARNING).
"""
import logging
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from src.config import StreamFitConfig  # noqa: E402
from src.service import StreamFitService  # noqa: E402
from fastmcp import FastMCP  # noqa: E402

logging.basicConfig(
    level=getattr(logging, os.getenv("LOG_LEVEL", "WARNING").upper(), logging.WARNING),
    stream=sys.stderr,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)

config = StreamFitConfig()
service = StreamFitService(config)  # allow_browser_login=True (MCP keeps re-login)

mcp = FastMCP("StreamFit MCP")


@mcp.tool()
def get_gym_info() -> str:
    """Get CrossFit 514 gym/channel information.

    Returns:
        JSON object with gym details (name, address, contact, settings).
    """
    return service.get_gym_info()


@mcp.tool()
def get_class_schedule(start_date: str | None = None, days: int = 7) -> str:
    """Fetch the upcoming class calendar.

    Args:
        start_date: ISO date string (YYYY-MM-DD), defaults to today.
        days: number of days to fetch (default 7).

    Returns:
        JSON object with class list: id, name, datetime, type, spots_left.
    """
    return service.get_class_schedule(start_date=start_date, days=days)


@mcp.tool()
def get_my_registrations(start_date: str | None = None, days: int = 14) -> str:
    """List MY booked classes at CrossFit 514 (registered=true) plus waitlist.

    Args:
        start_date: ISO date string (YYYY-MM-DD), defaults to today.
        days: number of days to scan (default 14).

    Returns:
        JSON with booked classes (name, datetime, coach, spots) and waitlist.
    """
    return service.get_my_registrations(start_date=start_date, days=days)


@mcp.tool()
def register_class(workout_id: str, channel_key_id: int | None = None,
                   class_type: str = "inPerson", direct_checkin: bool = False) -> str:
    """Register ME for a class (athlete flow, same as the app's Register button).

    NOTE: this has REAL side effects — it genuinely books the user.

    Args:
        workout_id: StreamFit workout ID (integer or string).
        channel_key_id: membership key id (auto-detected if omitted).
        class_type: 'inPerson' (default) or 'online'.
        direct_checkin: True to check in directly.

    Returns:
        JSON with status and registration confirmation.
    """
    return service.register_class(workout_id=workout_id, channel_key_id=channel_key_id,
                                  class_type=class_type, direct_checkin=direct_checkin)


@mcp.tool()
def cancel_registration(workout_id: str) -> str:
    """Cancel MY registration for a class (athlete flow, same as the app's Cancel).

    Args:
        workout_id: StreamFit workout ID (integer or string).

    Returns:
        JSON with status and cancellation confirmation.
    """
    return service.cancel_registration(workout_id=workout_id)


@mcp.tool()
def get_workout(workout_id: str) -> str:
    """Fetch full workout details (sections, exercises, coach notes).

    Args:
        workout_id: StreamFit workout ID (integer or string).

    Returns:
        Raw JSON response with full workout structure.
    """
    return service.get_workout(workout_id)


@mcp.tool()
def get_coach_notes(workout_id: str) -> str:
    """Extract and return coach notes from a specific workout.

    Args:
        workout_id: StreamFit workout ID (integer or string).

    Returns:
        Coach notes as a string, or "No coach notes found" message.
    """
    return service.get_coach_notes(workout_id)


@mcp.tool()
def get_auth_status() -> str:
    """Check StreamFit auth health: are the saved tokens still valid?

    Use this before a batch of operations to tell "broken session" apart from
    "the API said no". Does not trigger a re-login.

    Returns:
        JSON with status (valid/invalid/missing/error), user_id and email.
    """
    return service.auth_status()


if __name__ == "__main__":
    mcp.run(transport="stdio")