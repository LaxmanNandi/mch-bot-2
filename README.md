MCH-Inspired NIFTY Options Bot (Prototype)

This repository contains a minimal, working prototype of a "Conscious Trading Bot" inspired by the Mirrorâ€‘Coherence Hypothesis (MCH). It includes:

- MCH layers: RCI (coherence scoring), OIA (identity/guardrails), AT (authentication threshold)
- Strategy: Iron Condor (weekly options), with simple sizing and exits
- Execution: Paper broker (dryâ€‘run) and a simplistic backtester using synthetic data
- Configurable via YAML

Status: Prototype for demonstration and extension. Live brokerage not wired.

Quickstart

1) Install dependencies

```
python -m pip install -r requirements.txt
```

2) Run a demo backtest on synthetic data

```
python -m mch_bot backtest --config config.yaml --data data/sample_underlying.csv
```

3) Dryâ€‘run live loop (no broker actions)

```
python -m mch_bot live --config config.yaml --dry-run
```

Files

- `mch_bot/` â€” Bot package
- `config.yaml` â€” Editable config (instrument, risk, strategy, MCH)
- `data/sample_underlying.csv` â€” Synthetic underlying series (close + iv)

Notes

- Backtester uses Blackâ€‘Scholes pricing from underlying close and implied vol (iv) to approximate option premiums at entry/exit. This is illustrative, not productionâ€‘accurate.
- To connect to a real broker (e.g., Kite, Angel, Upstox), implement a new adapter under `mch_bot/brokers/` using `BrokerBase`.
- Zerodha Kite adapter included. Steps:
   1. Install deps: `python -m pip install -r requirements.txt`
   2. Get a request_token by logging into the Kite Connect app URL (as per Zerodha docs).
   3. Exchange token and store locally:
      `python -m mch_bot kite-auth --request-token YOUR_REQUEST_TOKEN --api-key YOUR_API_KEY --api-secret YOUR_API_SECRET`
      This writes `.secrets/kite.json` with an access token. You can alternatively set env vars `KITE_API_KEY`, `KITE_API_SECRET`, `KITE_ACCESS_TOKEN`.
   4. Set `execution.broker: kite` and `execution.dry_run: false` in `config.yaml` to send real orders.
   5. Verify tradingsymbol format. The prototype builds symbols like `NFO:NIFTY25OCT23500CE` using the next weekly expiry (weekday from `instrument.weekly_expiry_weekday`). If your broker uses different formatting, adjust `make_ts` in `mch_bot/engine.py:1` or use the instruments dump to map tokens directly.

Configuration tips

- Verify instrument details in `config.yaml`:
  - `instrument.symbol: NIFTY`
  - `instrument.underlying_symbol_zerodha: "NSE:NIFTY 50"`
  - `instrument.weekly_expiry_weekday: TUE`
  - `instrument.strike_step: 50`
- Market hours gating:
  - `market.open: 09:15`, `market.close: 15:30`, `market.holidays: []`, `timezone: Asia/Kolkata`
  - Live mode exits immediately if market is closed per config.

Live strike selection (by delta)

- Live mode estimates spot via `instrument.underlying_symbol_zerodha` (default `NSE:NIFTY 50`) and picks short strikes whose absolute Blackâ€‘Scholes delta is closest to `strategy.target_delta`. It uses `strategy.iv_assumption` as the implied vol unless you extend it to infer IV from the option chain. Wings are set by `strategy.wing_width_points`.
 - The live flow now:
   - Loads instruments once and resolves tradingsymbols from the dump (no string guessing)
   - Gets spot LTP and infers ATM IV from CE/PE LTPs (fallback to `strategy.iv_assumption`)
   - Scans strikes to pick trueâ€‘delta shorts and builds wings
   - Places entry LIMIT orders and monitors net buyback vs TP/SL
   - Sends offsetting close orders when TP/SL hit or timeout (see `execution.monitor_seconds`)

Caveats

- Holidays and special expiry shifts arenâ€™t handled. `instrument.weekly_expiry_weekday` controls the weekday used for weekly expiry selection.
- Zerodha quotes and instruments require a valid `access_token`; run `kite-auth` first.
 - The monitor loop is intentionally simple; for production, add robust order/fill tracking, error handling, and persistence.
 - The live cycle respects basic market hours from config. Adjust times/holidays as needed for tests.
- Always validate against exchange rules and your risk policy. This is not financial advice.

