from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from telegram import Update
from telegram.constants import ParseMode
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes

from .query import QueryEngine


SECRETS_DIR = Path('.secrets')
TELEGRAM_FILE = SECRETS_DIR / 'telegram.json'


def _load_token(env_var: str = 'TELEGRAM_BOT_TOKEN') -> Optional[str]:
    tok = os.getenv(env_var)
    if tok:
        return tok
    if TELEGRAM_FILE.exists():
        try:
            data = json.loads(TELEGRAM_FILE.read_text(encoding='utf-8'))
            return data.get('bot_token')
        except Exception:
            return None
    return None


def _save_token(token: str) -> None:
    SECRETS_DIR.mkdir(exist_ok=True)
    data = {}
    if TELEGRAM_FILE.exists():
        try:
            data = json.loads(TELEGRAM_FILE.read_text(encoding='utf-8'))
        except Exception:
            data = {}
    data['bot_token'] = token
    TELEGRAM_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')


def _allowed_chat_ids() -> set[int]:
    ids: set[int] = set()
    if TELEGRAM_FILE.exists():
        try:
            data = json.loads(TELEGRAM_FILE.read_text(encoding='utf-8'))
            for x in data.get('allowed_chat_ids', []):
                try:
                    ids.add(int(x))
                except Exception:
                    pass
        except Exception:
            pass
    env = os.getenv('TELEGRAM_ALLOWED_IDS')
    if env:
        for x in env.split(','):
            x = x.strip()
            if not x:
                continue
            try:
                ids.add(int(x))
            except Exception:
                pass
    # Single chat id env var support
    one = os.getenv('TELEGRAM_CHAT_ID')
    if one:
        try:
            ids.add(int(one))
        except Exception:
            pass
    return ids


def _store_allowed_chat_id(chat_id: int) -> None:
    SECRETS_DIR.mkdir(exist_ok=True)
    data = {}
    if TELEGRAM_FILE.exists():
        try:
            data = json.loads(TELEGRAM_FILE.read_text(encoding='utf-8'))
        except Exception:
            data = {}
    ids = set(data.get('allowed_chat_ids', []))
    ids.add(int(chat_id))
    data['allowed_chat_ids'] = sorted(list(map(int, ids)))
    TELEGRAM_FILE.write_text(json.dumps(data, indent=2), encoding='utf-8')


async def _send_text(update: Update, text: str, ctx: ContextTypes.DEFAULT_TYPE) -> None:
    if not update.effective_chat:
        return
    await ctx.bot.send_message(chat_id=update.effective_chat.id, text=text)


def _qe() -> QueryEngine:
    return QueryEngine(log_dir="logs", config_path="config.yaml")


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    msg = (
        "MCH Trading Bot — Telegram Interface\n"
        "Commands:\n"
        "/status — bot status\n"
        "/trades [N] — last N trades\n"
        "/whatif spot=26000 [vix=20] — simulate scenario\n"
        "/id — show your chat id (for allowlist)\n"
        "Or send a natural language question."
    )
    await _send_text(update, msg, context)


async def status(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    # Access control
    allowed = _allowed_chat_ids()
    if allowed and update.effective_chat and update.effective_chat.id not in allowed:
        await _send_text(update, "Unauthorized chat. Ask admin to /allow your chat id.", context)
        return
    qe = _qe()
    parsed = qe.parse_question("status")
    resp = qe.execute_query(parsed)
    await _send_text(update, resp.text, context)


async def trades(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = _allowed_chat_ids()
    if allowed and update.effective_chat and update.effective_chat.id not in allowed:
        await _send_text(update, "Unauthorized chat. Ask admin to /allow your chat id.", context)
        return
    qe = _qe()
    n = None
    if context.args:
        try:
            n = int(context.args[0])
        except Exception:
            n = None
    parsed = qe.parse_question(f"trades last {n}" if n else "trades")
    resp = qe.execute_query(parsed)
    await _send_text(update, "```\n" + resp.text + "\n```", context)


async def whatif(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = _allowed_chat_ids()
    if allowed and update.effective_chat and update.effective_chat.id not in allowed:
        await _send_text(update, "Unauthorized chat. Ask admin to /allow your chat id.", context)
        return
    qe = _qe()
    args = " ".join(context.args) if context.args else ""
    parsed = qe.parse_question(f"what if {args}")
    resp = qe.execute_query(parsed)
    await _send_text(update, resp.text, context)


async def any_text(update: Update, context: ContextTypes.DEFAULT_TYPE) -> None:
    allowed = _allowed_chat_ids()
    if allowed and update.effective_chat and update.effective_chat.id not in allowed:
        await _send_text(update, "Unauthorized chat. Ask admin to /allow your chat id.", context)
        return
    qe = _qe()
    q = update.message.text if update.message else "status"
    parsed = qe.parse_question(q)
    resp = qe.execute_query(parsed)
    await _send_text(update, resp.text, context)


def run(token: Optional[str] = None) -> None:
    tok = token or _load_token()
    if not tok:
        raise RuntimeError("Telegram bot token not found. Provide --token or set TELEGRAM_BOT_TOKEN or .secrets/telegram.json")

    app = Application.builder().token(tok).build()

    app.add_handler(CommandHandler("start", start))
    app.add_handler(CommandHandler("help", start))
    # Utility: chat id
    async def chat_id_cmd(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
        if update.effective_chat:
            await _send_text(update, f"Your chat id: {update.effective_chat.id}", ctx)
    app.add_handler(CommandHandler("id", chat_id_cmd))
    app.add_handler(CommandHandler("status", status))
    app.add_handler(CommandHandler("trades", trades))
    app.add_handler(CommandHandler("whatif", whatif))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, any_text))

    logging.getLogger(__name__).info("Telegram bot is running. Press Ctrl+C to stop.")
    app.run_polling()


def store_token(token: str) -> None:
    _save_token(token)


def store_setup(token: str, chat_id: Optional[int]) -> None:
    """Store token and optionally allow a chat id in one go."""
    _save_token(token)
    if chat_id is not None:
        _store_allowed_chat_id(int(chat_id))


# Allowlist helpers for CLI
def allow_chat(chat_id: int) -> None:
    _store_allowed_chat_id(chat_id)
