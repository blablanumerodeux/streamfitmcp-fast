#!/usr/bin/env python3
"""
StreamFit MCP Server — FastMCP implementation.

Wraps the StreamFit API (CrossFit 514) with MCP tools:
  - get_gym_info()           — gym/channel info
  - get_class_schedule()     — upcoming class calendar
  - get_workout()            — full workout details by ID
  - get_coach_notes()        — extract coach notes from a workout

Run:
    cp .env.example .env   # fill in STREAMFIT_* tokens
    pip install -r requirements.txt
    python main.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

from src.config import StreamFitConfig
from src.service import StreamFitService
from fastmcp import FastMCP

config = StreamFitConfig(
    base_url=os.getenv("STREAMFIT_BASE_URL", "https://api.streamfit.com"),
    channel_id=os.getenv("STREAMFIT_CHANNEL_ID", "812"),
    access_token=os.getenv("STREAMFIT_ACCESS_TOKEN", ""),
    client=os.getenv("STREAMFIT_CLIENT", ""),
    expiry=os.getenv("STREAMFIT_EXPIRY", ""),
    uid=os.getenv("STREAMFIT_UID", ""),
)
service = StreamFitService(config)

mcp = FastMCP("StreamFit MCP")


@mcp.tool()
def get_gym_info() -> str:
    """
    Get CrossFit 514 gym/channel information.

    Returns:
        JSON object with gym details (name, address, contact, settings).
    """
    return service.get_gym_info()


@mcp.tool()
def get_class_schedule(start_date: str | None = None, days: int = 7) -> str:
    """
    Fetch the upcoming class calendar.

    Args:
        start_date: ISO date string (YYYY-MM-DD), defaults to today.
        days: number of days to fetch (default 7, max ~30).

    Returns:
        JSON object with class list: id, name, datetime, type, spots_left.
    """
    return service.get_class_schedule(start_date=start_date, days=days)


@mcp.tool()
def get_my_registrations(start_date: str | None = None, days: int = 14) -> str:
    """
    List MY booked classes at CrossFit 514 (registered=true) plus waitlist entries.

    Args:
        start_date: ISO date string (YYYY-MM-DD), defaults to today.
        days: number of days to scan (default 14).

    Returns:
        JSON with booked classes (name, datetime, coach, spots) and waitlist.
    """
    return service.get_my_registrations(start_date=start_date, days=days)


@mcp.tool()
def get_workout(workout_id: str) -> str:
    """
    Fetch full workout details (sections, exercises, coach notes).

    Args:
        workout_id: StreamFit workout ID (integer or string).

    Returns:
        Raw JSON response with full workout structure.
    """
    return service.get_workout(workout_id)


@mcp.tool()
def get_coach_notes(workout_id: str) -> str:
    """
    Extract and return coach notes from a specific workout.

    Args:
        workout_id: StreamFit workout ID (integer or string).

    Returns:
        Coach notes as a string, or "No coach notes found" message.
    """
    return service.get_coach_notes(workout_id)


if __name__ == "__main__":
    mcp.run(transport="stdio")
