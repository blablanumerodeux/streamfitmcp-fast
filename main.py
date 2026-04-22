#!/usr/bin/env python3
"""
StreamFit MCP Server — FastMCP implementation.

Authenticates with StreamFit via email + PIN (Devise token auth) and exposes:
  - get_workout(workout_id)  — full workout data as JSON
  - get_coach_notes(workout_id) — extracted coach notes from workout sections

Run:
    cp .env.example .env   # fill in STREAMFIT_EMAIL and STREAMFIT_PIN
    pip install -r requirements.txt
    python main.py
"""

import os
from dotenv import load_dotenv

load_dotenv()

from src.config import StreamFitConfig
from src.service import StreamFitService
from fastmcp import FastMCP

# ── Bootstrap ────────────────────────────────────────────────────────────────

config = StreamFitConfig(
    base_url=os.getenv("STREAMFIT_BASE_URL", "https://api.streamfit.com"),
    email=os.getenv("STREAMFIT_EMAIL", ""),
    pin=os.getenv("STREAMFIT_PIN", ""),
)
service = StreamFitService(config)

mcp = FastMCP(
    "StreamFit MCP",
    dependencies=[
        "httpx>=0.27.0",
        "python-dotenv>=1.0.0",
    ],
)


# ── Tools ─────────────────────────────────────────────────────────────────────


@mcp.tool()
def get_workout(workout_id: str) -> str:
    """
    Retrieve full workout data from StreamFit by workout ID.

    Args:
        workout_id: StreamFit workout identifier (e.g. '4195631-wod')

    Returns:
        Raw workout JSON string containing all sections, exercises, sets, and
        any coach notes embedded in sections.
    """
    if not workout_id or not workout_id.strip():
        return '{"error": "workout_id cannot be empty"}'

    return service.get_workout(workout_id.strip())


@mcp.tool()
def get_coach_notes(workout_id: str) -> str:
    """
    Extract coach notes from a workout's sections.

    Use this to retrieve coaching instructions, tips, and notes the coach
    attached to individual sections of the workout.

    Args:
        workout_id: StreamFit workout identifier (e.g. '4195631-wod')

    Returns:
        All non-empty coach notes joined by double newlines, or a message
        indicating no notes were found.
    """
    if not workout_id or not workout_id.strip():
        return "Error: workout_id cannot be empty"

    return service.get_coach_notes(workout_id.strip())


# ── Entry point ───────────────────────────────────────────────────────────────

if __name__ == "__main__":
    import sys

    # Check required env vars before starting
    missing = [k for k in ("STREAMFIT_EMAIL", "STREAMFIT_PIN") if not os.getenv(k)]
    if missing:
        print(
            f"WARNING: Missing environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in your credentials.\n",
            file=sys.stderr,
        )

    # Run as stdio server (default for MCP)
    mcp.run(transport="stdio")
