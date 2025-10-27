from __future__ import annotations

import json
import logging
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import requests

from .auth.kite_auth import load_creds_from_env, login_and_get_request_token, exchange_request_token_for_access
from .railway_client import update_env_variable, restart_railway_service


log = logging.getLogger("token_refresh")
STATE_FILE = Path(".runtime/token_state.json")


def _send_telegram(text: str) -> None:
    tok = os.getenv("TELEGRAM_BOT_TOKEN")
    chat = os.getenv("TELEGRAM_CHAT_ID")
    if not tok or not chat:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{tok}/sendMessage",
            json={"chat_id": int(chat), "text": text, "parse_mode": "HTML"},
            timeout=10,
        )
    except Exception:
        pass


def _save_state(d: dict) -> None:
    try:
        STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
        STATE_FILE.write_text(json.dumps(d, indent=2), encoding="utf-8")
    except Exception:
        pass


def _load_state() -> dict:
    try:
        if STATE_FILE.exists():
            return json.loads(STATE_FILE.read_text(encoding="utf-8"))
    except Exception:
        pass
    return {}


def refresh_token_once() -> Optional[str]:
    creds = load_creds_from_env()
    # 1) Get request_token via Playwright
    req_token = login_and_get_request_token(creds)
    # 2) Exchange for access_token via Kite API
    access_token = exchange_request_token_for_access(creds, req_token)
    # 3) Persist locally (.secrets/kite.json) for running processes
    try:
        secrets_dir = Path('.secrets')
        secrets_dir.mkdir(exist_ok=True)
        path = secrets_dir / 'kite.json'
        data = {"api_key": creds.api_key, "api_secret": creds.api_secret, "access_token": access_token}
        path.write_text(json.dumps(data, indent=2), encoding='utf-8')
    except Exception as e:
        log.warning(f"Failed to persist local token: {e}")
    return access_token


def propagate_to_railway(access_token: str) -> dict:
    """Update Railway env var and restart service.

    Returns dict with 'env_updated' and 'restarted' booleans.
    """
    svc = os.getenv("RAILWAY_SERVICE_ID")
    tok = os.getenv("RAILWAY_TOKEN")
    result = {"env_updated": False, "restarted": False}

    if not svc or not tok:
        log.warning("Railway credentials not found (RAILWAY_SERVICE_ID or RAILWAY_TOKEN)")
        return result

    # Step 1: Update environment variable
    env_ok = update_env_variable(svc, tok, {"KITE_ACCESS_TOKEN": access_token})
    result["env_updated"] = env_ok

    if not env_ok:
        log.warning("Failed to update Railway env var, skipping restart")
        return result

    log.info("Railway env var updated, triggering service restart...")

    # Step 2: Restart service to pick up new env var
    # Small delay to ensure env var update is propagated
    time.sleep(2)
    restart_ok = restart_railway_service(svc, tok)
    result["restarted"] = restart_ok

    if restart_ok:
        log.info("Railway service restart triggered successfully")
    else:
        log.warning("Railway service restart failed - manual restart may be needed")

    return result


def run_refresh_workflow() -> None:
    start = datetime.now(timezone.utc)
    try:
        acc = refresh_token_once()
        if not acc:
            raise RuntimeError("Token refresh returned None")

        railway_result = propagate_to_railway(acc)
        st = _load_state()
        st.update({
            "last_refresh_utc": start.isoformat(),
            "access_token_tail": acc[-6:],
            "railway_env_updated": railway_result["env_updated"],
            "railway_restarted": railway_result["restarted"],
        })
        _save_state(st)

        # Enhanced Telegram notification
        msg = f"✅ <b>Kite token refreshed</b>\n"
        msg += f"Tail: {acc[-6:]}\n"
        msg += f"Railway env updated: {railway_result['env_updated']}\n"
        msg += f"Railway restarted: {railway_result['restarted']}"

        if railway_result["env_updated"] and not railway_result["restarted"]:
            msg += "\n⚠️ Service restart failed - manual restart needed!"

        _send_telegram(msg)
    except Exception as e:
        _send_telegram(f"🚨 <b>Kite token refresh failed</b>\nError: {e}")
        raise


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")
    run_refresh_workflow()

