from __future__ import annotations

import os
import re
import logging
from dataclasses import dataclass
from typing import Optional

from kiteconnect import KiteConnect


log = logging.getLogger(__name__)


@dataclass
class KiteCreds:
    api_key: str
    api_secret: str
    username: str
    password: str
    totp_secret: Optional[str] = None


def _env_or_raise(name: str) -> str:
    v = os.getenv(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def load_creds_from_env() -> KiteCreds:
    return KiteCreds(
        api_key=_env_or_raise("KITE_API_KEY"),
        api_secret=_env_or_raise("KITE_API_SECRET"),
        username=_env_or_raise("KITE_USERNAME"),
        password=_env_or_raise("KITE_PASSWORD"),
        totp_secret=os.getenv("KITE_TOTP_SECRET"),
    )


def build_login_url(api_key: str) -> str:
    return f"https://kite.trade/connect/login?api_key={api_key}&v=3"


def login_and_get_request_token(creds: KiteCreds, timeout_ms: int = 60000) -> str:
    """Headless login via Playwright to get request_token from redirect URL."""
    from playwright.sync_api import sync_playwright
    import pyotp

    login_url = build_login_url(creds.api_key)
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context()
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        page.goto(login_url)

        # Fill username/password
        if page.locator("input#userid").count():
            page.fill("input#userid", creds.username)
        else:
            page.fill("input[name='user_id']", creds.username)
        page.fill("input#password, input[name='password']", creds.password)
        page.click("button[type='submit'], button:has-text('Login')")

        # If directly redirected, capture token
        if 'request_token=' in page.url:
            m = re.search(r"request_token=([^&]+)", page.url)
            if not m:
                raise RuntimeError("request_token not found in redirect URL")
            return m.group(1)

        # 2FA (TOTP) if prompted
        if creds.totp_secret:
            code = pyotp.TOTP(creds.totp_secret).now()
            # Try common selectors
            for sel in ["input#totp", "input[name='totp']", "input[name='otp']", "input[type='text']"]:
                if page.locator(sel).count():
                    page.fill(sel, str(code))
                    break
            page.click("button[type='submit'], button:has-text('Continue'), button:has-text('Verify')")

        # Wait for redirect and extract token
        page.wait_for_load_state('networkidle')
        # Sometimes URL updates asynchronously; check a few times
        for _ in range(10):
            if 'request_token=' in page.url:
                m = re.search(r"request_token=([^&]+)", page.url)
                if not m:
                    break
                return m.group(1)
            page.wait_for_timeout(500)

        raise RuntimeError("Failed to obtain request_token from Kite login flow")


def exchange_request_token_for_access(creds: KiteCreds, request_token: str) -> str:
    kite = KiteConnect(api_key=creds.api_key)
    data = kite.generate_session(request_token, api_secret=creds.api_secret)
    return data["access_token"]

