import argparse
from pathlib import Path

from .config import load_config
from .engine import run_backtest, run_live
from .brokers.zerodha_kite import KiteBroker
from kiteconnect import KiteConnect


def main() -> None:
    parser = argparse.ArgumentParser(prog="mch_bot", description="MCH-Inspired NIFTY Options Bot (Prototype)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    # Backtest
    p_bt = sub.add_parser("backtest", help="Run backtest on CSV data")
    p_bt.add_argument("--config", required=True, type=Path)
    p_bt.add_argument("--data", required=True, type=Path, help="CSV with columns: timestamp,close,iv(optional)")

    # Live
    p_live = sub.add_parser("live", help="Run live loop (dry-run by default)")
    p_live.add_argument("--config", required=True, type=Path)
    p_live.add_argument("--dry-run", action="store_true", help="Force dry-run (no broker actions)")

    # Live continuous loop
    p_live_loop = sub.add_parser("live-loop", help="Continuous market-hours scanning and re-entry")
    p_live_loop.add_argument("--config", required=True, type=Path)
    p_live_loop.add_argument("--interval", required=False, type=int, default=60, help="Seconds between scans")

    # Kite auth
    p_auth = sub.add_parser("kite-auth", help="Exchange request_token for access_token and save locally")
    p_auth.add_argument("--api-key", required=False, help="Kite API key (optional if in env or secrets)")
    p_auth.add_argument("--api-secret", required=False, help="Kite API secret (optional if in env or secrets)")
    p_auth.add_argument("--request-token", required=True, help="Request token from Kite login flow")

    p_login = sub.add_parser("kite-login-url", help="Print the Kite Connect login URL for your API key")
    p_login.add_argument("--api-key", required=True, help="Kite API key")

    # Query interface
    p_query = sub.add_parser("query", help="Ask a natural language question about the bot")
    p_query.add_argument("question", nargs='+', help="Natural language question")

    # Interactive chat
    sub.add_parser("chat", help="Interactive query mode")

    # Telegram interface
    p_tg = sub.add_parser("telegram", help="Run Telegram query interface (polling)")
    p_tg.add_argument("--token", required=False, help="Telegram bot token (optional if stored or in env)")
    p_tg_setup = sub.add_parser("telegram-setup", help="Store Telegram bot token (and optional chat id) in .secrets/telegram.json")
    p_tg_setup.add_argument("--token", required=False, help="Telegram bot token")
    p_tg_setup.add_argument("--chat-id", required=False, type=int, help="Allow this chat id")
    p_tg_allow = sub.add_parser("telegram-allow", help="Allow a chat id to use the Telegram bot")
    p_tg_allow.add_argument("--chat-id", required=True, type=int)
    p_tg_alerts = sub.add_parser("telegram-alerts", help="Send push alerts by tailing logs/latest.log")
    p_tg_alerts.add_argument("--log", required=False, default="logs/latest.log")

    args = parser.parse_args()

    if args.cmd == "backtest":
        cfg = load_config(args.config)
        run_backtest(cfg, data_path=args.data)
        return

    if args.cmd == "live":
        cfg = load_config(args.config)
        run_live(cfg, force_dry_run=bool(args.dry_run))
        return

    if args.cmd == "live-loop":
        from .engine import run_live_loop
        cfg = load_config(args.config)
        run_live_loop(cfg, interval_seconds=int(args.interval))
        return

    if args.cmd == "kite-auth":
        # Allow passing either a bare token or the full redirect URL
        raw = args.request_token.strip().strip('"').strip("'")
        token = raw
        if raw.startswith("http") or "request_token=" in raw:
            import re
            m = re.search(r"request_token=([^&]+)", raw)
            if not m:
                print("Could not find request_token in the provided URL. Please paste the full redirect URL from the browser.")
                return
            token = m.group(1)
        kb = KiteBroker(api_key=args.api_key, api_secret=args.api_secret)
        try:
            kb.exchange_request_token(token)
        except Exception as e:
            print("Kite auth failed: ", e)
            print("Hints: Use a fresh request_token, exchange immediately, and ensure API key/secret match your app.")
            return
        print("Stored access_token for Kite in .secrets/kite.json")
        return

    if args.cmd == "kite-login-url":
        kc = KiteConnect(api_key=args.api_key)
        print(kc.login_url())
        return

    if args.cmd == "query":
        from .query import QueryEngine
        qe = QueryEngine(log_dir="logs", config_path="config.yaml")
        q = " ".join(args.question)
        parsed = qe.parse_question(q)
        resp = qe.execute_query(parsed)
        print(resp.text)
        return

    if args.cmd == "chat":
        from .query import QueryEngine
        qe = QueryEngine(log_dir="logs", config_path="config.yaml")
        print("MCH Bot chat - type 'exit' to quit.")
        while True:
            try:
                s = input("> ")
            except EOFError:
                break
            if not s or s.strip().lower() in ("exit", "quit"):
                break
            parsed = qe.parse_question(s)
            resp = qe.execute_query(parsed)
            print(resp.text)
        return

    if args.cmd == "telegram":
        from .telegram_query import run as run_tg
        run_tg(token=args.token)
        return

    if args.cmd == "telegram-setup":
        from .telegram_query import store_setup
        tok = args.token
        if not tok:
            try:
                tok = input("Enter Telegram bot token: ").strip()
            except EOFError:
                tok = None
        if not tok:
            print("Token is required. Pass --token or provide via prompt.")
            return
        store_setup(tok, args.chat_id)
        if args.chat_id is not None:
            print(f"Stored token and allowed chat id {args.chat_id} in .secrets/telegram.json")
        else:
            print("Stored Telegram bot token in .secrets/telegram.json")
        return

    if args.cmd == "telegram-allow":
        from .telegram_query import allow_chat
        allow_chat(args.chat_id)
        print(f"Allowed chat id {args.chat_id}.")
        return

    if args.cmd == "telegram-alerts":
        from .telegram_alerts import tail_file
        # Default patterns for useful events
        patterns = [
            "Live Market Data:",
            "Recommended Iron Condor:",
            "Order:",
            "Hit TP:",
            "Hit SL:",
            "IC validation failed",
            "No eligible IC",
        ]
        tail_file(Path(args.log), patterns)
        return

    parser.print_help()
