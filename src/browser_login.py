"""Browser-based StreamFit login.

The API's reCAPTCHA v3 scores headless/programmatic captcha tokens too low
("Recaptcha verification failed" 403), but driving the REAL login UI in
Chromium passes. This module:

1. Tries token validation first (saved Devise tokens are long-lived).
2. On failure, drives go.streamfit.com: email -> Let's Go -> PIN -> Confirm
   -> MFA code (read from Gmail via the gws CLI) -> Confirm.
3. Captures the Devise auth headers (access-token, client, uid, expiry) from
   post-login API traffic and saves them to the tokens file.
"""
import json
import logging
import re
import subprocess
import time
from email.utils import parsedate_to_datetime
from typing import Any

logger = logging.getLogger(__name__)

APP_URL = "https://go.streamfit.com"
GWS_BIN = "/home/linuxbrew/.linuxbrew/bin/gws"


class BrowserLogin:
    def __init__(self, email: str, pin: str, tokens_path: str):
        self.email = email
        self.pin = pin
        self.tokens_path = tokens_path

    # ── Public API ────────────────────────────────────────────────────────────

    def login(self) -> dict[str, Any]:
        """Run the full browser login. Returns saved token dict or error."""
        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            return {"status": "error", "message": "playwright not installed (pip install playwright && playwright install chromium)"}

        start = time.time() - 5
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True, args=["--no-sandbox"])
            ctx = browser.new_context(
                user_agent="Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36",
                viewport={"width": 1280, "height": 900},
            )
            page = ctx.new_page()
            auth_headers: dict[str, str] = {}

            def on_response(resp):
                if "api.streamfit.com" not in resp.url:
                    return
                req = resp.request
                hdrs = {h: req.headers.get(h, "") for h in ("access-token", "client", "uid", "expiry")}
                if hdrs.get("access-token") and not auth_headers:
                    auth_headers.update(hdrs)

            page.on("response", on_response)

            try:
                page.goto(APP_URL, wait_until="networkidle", timeout=60000)
                page.wait_for_timeout(2000)
                page.fill("input[type=email]", self.email)
                page.click("button:has-text(\"Let's Go!\")")
                page.wait_for_timeout(2500)

                pins = page.query_selector_all("input[type=password]")
                if not pins:
                    return {"status": "error", "message": "PIN input not found on login page"}
                pins[0].type(self.pin, delay=80)
                page.click("button:has-text(\"Confirm\")")
                page.wait_for_timeout(3000)

                # MFA step (code sent by email)
                mfa_input = page.query_selector("input[placeholder*='code' i]")
                if mfa_input:
                    code = self._fetch_mfa_code(start)
                    if not code:
                        return {"status": "error", "message": "MFA code not found in Gmail within timeout"}
                    mfa_input.type(code, delay=60)
                    page.click("button:has-text(\"Confirm\")")
                    page.wait_for_timeout(8000)
            finally:
                browser.close()

        if not auth_headers.get("access-token"):
            return {"status": "error", "message": "Login completed but no auth headers captured"}

        tokens = dict(auth_headers)
        tokens["email"] = self.email
        with open(self.tokens_path, "w") as f:
            json.dump(tokens, f, indent=2)
        logger.info("StreamFit tokens saved to %s", self.tokens_path)
        return {"status": "authenticated", "method": "browser_mfa", "tokens_path": self.tokens_path}

    # ── MFA code via Gmail ────────────────────────────────────────────────────

    def _fetch_mfa_code(self, after_epoch: float, max_wait: int = 90) -> str | None:
        """Poll Gmail (via gws CLI) for the StreamFit verification code email."""
        deadline = time.time() + max_wait
        while time.time() < deadline:
            code = self._check_gmail_for_code(after_epoch)
            if code:
                return code
            time.sleep(6)
        return None

    def _check_gmail_for_code(self, after_epoch: float) -> str | None:
        try:
            r = subprocess.run(
                [GWS_BIN, "gmail", "users", "messages", "list", "--params",
                 json.dumps({"userId": "me", "q": "from:streamfit.com newer_than:1d", "maxResults": 3})],
                capture_output=True, text=True, timeout=60)
            ids = re.findall(r'"id":\s*"([a-f0-9]+)"', r.stdout)
            for mid in ids:
                r2 = subprocess.run(
                    [GWS_BIN, "gmail", "+read", "--id", mid, "--headers"],
                    capture_output=True, text=True, timeout=60)
                m = re.search(r"Date:\s*(.+)", r2.stdout)
                if not m:
                    continue
                try:
                    dt = parsedate_to_datetime(m.group(1)).timestamp()
                except Exception:
                    continue
                if dt > after_epoch:
                    cm = re.search(r"enter the code below:\s*(\d{4,8})", r2.stdout)
                    if cm:
                        return cm.group(1)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning("gws gmail poll failed: %s", e)
        return None
