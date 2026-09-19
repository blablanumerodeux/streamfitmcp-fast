# StreamFit MCP (fast)

FastMCP server wrapping the StreamFit API for **CrossFit 514** (channel 812) —
plus the shared service layer used by Hermes cron scripts.

## Tools

| Tool | What it does |
|---|---|
| `get_gym_info` | Gym/channel details |
| `get_class_schedule(start_date?, days=7)` | Upcoming class calendar |
| `get_my_registrations(start_date?, days=14)` | MY booked classes + waitlist |
| `register_class(workout_id, channel_key_id?, class_type?, direct_checkin?)` | Register (athlete flow) |
| `cancel_registration(workout_id)` | Cancel (athlete flow) |
| `get_workout(workout_id)` | Full workout details |
| `get_coach_notes(workout_id)` | Coach notes from a workout |
| `get_auth_status()` | Token/health check (no side effects) |

`register_class` has **real side effects** — it genuinely books the user. Verify
`registered` before and after any test, and confirm the inverse (`cancel_registration`)
works first.

## Auth

The old `POST /api/v1/new/auth/sign_in` PIN flow is **dead** (`400 Update your app`).
Current flow: reCAPTCHA v3 → `federate` → `verify_pin` → **`verify_mfa`** (6-digit code
by email) → Devise tokens in response headers.

Programmatic captcha tokens score too low (`403 Recaptcha verification failed`) — only a
**real browser session** passes. So `src/browser_login.py` drives the actual login UI in
headless Chromium and reads the MFA code from Gmail (`gws` CLI). Tokens are saved to
`.tokens.json` (gitignored) and reused while valid.

> MFA emails are rate-limited (~5 logins/day). `StreamFitService(allow_browser_login=False)`
> — the default for cron scripts — fails fast instead of burning a login. The MCP server
> itself keeps browser login enabled.

## Key endpoints (verified)

| Purpose | Endpoint |
|---|---|
| Token check (`data.id` = numeric user id) | `GET /api/v1/auth/validate_token` |
| Gym info | `GET /api/v1/channels/{id}` |
| Full schedule | `GET /api/v1/channels/{id}/calendar_workouts` |
| MY calendar (`registered` flag) | `GET /api/v1/users/calendar/workouts_by_day` |
| Register status for a class | `GET /api/v1/workouts_users/{workoutId}/register_status/{userId}` |
| Workout detail | `GET /api/v1/workouts/{workoutId}` |
| **Register** | `POST /api/v1/workouts/{id}/purchase` `{workoutId, type, channelKeyId, directCheckin}` |
| **Cancel** | `POST /api/v1/workouts/{id}/refund` `{childId: null}` |

The athlete UI books via a misleadingly-named **purchase** endpoint and unbooks via
**refund**. Admin/coach endpoints (`/channel_members/.../register`,
`/workouts_users/{id}/inactivate_user`) return 403/500 for an athlete session — do not use.

## Run

```bash
# stdio transport (how Hermes launches it)
/root/.hermes/hermes-agent/venv/bin/python main.py

# IMPORTANT: the venv is required — system python3 has no fastmcp.
```

Registered in Hermes as MCP server **`streamfit`** (`hermes mcp add`, see config.yaml
`mcp_servers.streamfit`), exposing tools as `mcp__streamfit__<tool>`. Verify with
`hermes mcp test streamfit`.

`main.py` never prints to stdout (that's the MCP protocol channel); logging goes to
stderr at `LOG_LEVEL` (default `WARNING`).

## Layout

```
main.py              FastMCP entry point (8 tools)
src/config.py        StreamFitConfig — env + .tokens.json load/save
src/service.py       StreamFitService — auth + all API calls
src/browser_login.py Headless Chromium login + Gmail MFA reader
```

Cron scripts in `~/.hermes/scripts/` share this code through `sf_lib.py` (imports
`src.service` directly — never starts the MCP server).