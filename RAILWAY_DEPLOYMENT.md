# MCH Bot 3.0 - Railway Deployment Guide

## Overview
This is **MCH Bot 3.0 (Momentum Premium Buyer)** - a systematic options trading bot that runs independently from Bot 2.0 (Iron Condor).

## Prerequisites
- Railway account connected to GitHub
- GitHub repository: `mch-bot-3-momentum`
- Zerodha Kite API credentials
- Telegram Bot credentials

## Deployment Steps

### 1. Create New Railway Service

1. Go to [Railway Dashboard](https://railway.app/dashboard)
2. Click **"New Project"**
3. Select **"Deploy from GitHub repo"**
4. Choose repository: `LaxmanNandi/mch-bot-3-momentum`
5. Railway will auto-detect Python and use `railway.json` configuration

### 2. Configure Environment Variables

Add these environment variables in Railway dashboard:

```bash
# Zerodha Kite API
KITE_API_KEY=your_api_key_here
KITE_API_SECRET=your_api_secret_here
KITE_ACCESS_TOKEN=your_access_token_here

# Telegram
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=your_chat_id_here
TELEGRAM_MODE=CONFIRM

# Trading Configuration
BROKER_MODE=PAPER
CAPITAL=100000
```

**IMPORTANT:**
- Keep `BROKER_MODE=PAPER` initially to test
- Change to `LIVE` only after successful paper trading
- Access token expires daily at 6 AM IST - use token refresher

### 3. Deploy

1. Railway will automatically deploy after environment variables are set
2. Monitor logs in Railway dashboard
3. Bot will send Telegram startup message when ready

### 4. Verify Deployment

Check Railway logs for:
```
========================================
BOT 3.0 STARTUP - Momentum Premium Buyer
========================================
Configuration loaded successfully
Master Portfolio Controller initialized
Telegram connected: @your_username
Status: ACTIVE
Mode: PAPER TRADING
========================================
```

## Bot 3.0 vs Bot 2.0

### Bot 2.0 (Iron Condor)
- Repository: `iron-condor-bot`
- Railway service: `iron-condor-bot`
- Strategy: Range-bound premium selling
- Active in: RANGING/VOLATILE markets

### Bot 3.0 (Momentum)
- Repository: `mch-bot-3-momentum`
- Railway service: `mch-bot-3-momentum` (NEW)
- Strategy: Directional premium buying
- Active in: TRENDING markets

### Master Portfolio Controller
Both bots use the **Master Portfolio Controller** which ensures:
- Only ONE bot trades at a time
- Bot selection based on market regime classification
- No conflicts between Bot 2.0 and Bot 3.0

## Token Management

### Daily Token Refresh (Required)

Kite access tokens expire daily at 6 AM IST. Two options:

**Option 1: Manual Refresh**
1. Run `python generate_token_now.py` locally at 6 AM
2. Update `KITE_ACCESS_TOKEN` on Railway
3. Restart the service

**Option 2: Auto Refresh (Recommended)**
See `momentum_bot/execution/token_refresher.py` for automatic refresh setup using Playwright.

## Monitoring

### Telegram Notifications
Bot sends notifications for:
- Startup/shutdown
- Market regime changes
- Trade signals (CONFIRM mode requires approval)
- Position entries/exits
- Daily P&L reports
- Error alerts

### Railway Logs
Monitor Railway logs for:
- Master Portfolio Controller decisions
- Regime classification changes
- API errors
- Risk limit breaches

## Troubleshooting

### Bot Not Starting
- Check environment variables are set correctly
- Verify Kite access token is valid
- Check Railway logs for errors

### No Trades Executing
- Verify `BROKER_MODE` is set (PAPER or LIVE)
- Check Master Portfolio Controller regime decision
- Bot 3.0 only trades in TRENDING markets
- Verify capital and risk limits in logs

### Token Expired Error
- Access token expired (happens daily at 6 AM IST)
- Generate new token: `python generate_token_now.py`
- Update `KITE_ACCESS_TOKEN` on Railway
- Restart service

### Both Bots Trading
- This should NEVER happen
- Master Portfolio Controller prevents this
- Check logs for regime classification
- If both active, report bug immediately

## Configuration

Edit `config_bot3.yaml` to customize:
- Capital allocation
- Position sizing
- Entry/exit rules
- Risk limits
- Telegram mode (CONFIRM vs AUTO)

After changes:
1. Commit to GitHub
2. Railway auto-deploys
3. Verify in Telegram startup message

## Support

For issues:
1. Check Railway logs first
2. Verify environment variables
3. Test locally with `python main_bot3.py`
4. Check Telegram for error messages

## Important Notes

1. **NO ROLLING**: Bot 3.0 does NOT average down on losing positions
2. **Independent Services**: Bot 2.0 and Bot 3.0 run as separate Railway services
3. **Master Controller**: Ensures only one bot active at a time
4. **Paper Trading**: Always test in PAPER mode first
5. **Token Expiry**: Tokens expire daily - plan for refresh

## Architecture

```
Railway Service: mch-bot-3-momentum
├── main_bot3.py (entry point)
├── momentum_bot/
│   ├── core/ (config, constants)
│   ├── data/ (market data, indicators)
│   ├── signals/ (momentum, regime, confidence)
│   ├── strategy/ (risk, position, exits)
│   ├── execution/ (broker, token refresh)
│   ├── portfolio/ (master controller)
│   └── monitoring/ (telegram, logger)
├── config_bot3.yaml
└── requirements_bot3.txt
```

## Next Steps After Deployment

1. Monitor first 2-3 days in PAPER mode
2. Verify regime classification logic
3. Check position sizing accuracy
4. Validate exit rules working correctly
5. Switch to LIVE mode if satisfied

---

**Deployed by:** LaxmanNandi
**Repository:** github.com/LaxmanNandi/mch-bot-3-momentum
**Railway Service:** mch-bot-3-momentum
