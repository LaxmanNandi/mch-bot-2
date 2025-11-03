# MCH Bot 3.0 - Momentum Premium Buyer

**A systematic options trading bot for momentum-based premium buying on NIFTY.**

---

## 🎯 Overview

MCH Bot 3.0 is a momentum-based options trading system that buys CALL/PUT options during strong trending markets. It implements two **critical fixes** from Gemini AI's strategic analysis:

### ✅ **Critical Fix #1: NO Rolling Logic**
- Position rolling has been **completely removed**
- Rolling = averaging down on losing positions (contradicts momentum strategy)
- Each position is independent and cannot be "rolled" to next expiry

### ✅ **Critical Fix #2: Master Portfolio Controller**
- **Only ONE bot active at a time** (Bot 2.0 Iron Condor OR Bot 3.0 Momentum)
- Prevents cross-bot conflicts
- Regime-based strategy selection:
  - **TRENDING** → Bot 3.0 Momentum (active)
  - **RANGING/VOLATILE** → Bot 2.0 Iron Condor (active)
  - **CHOPPY** → No bot active (cash)

---

## 📊 Strategy Highlights

### Entry Logic (Gemini's 5-Factor Model)
1. **Regime** - Trending market (ADX > 25, clear direction)
2. **Timing** - DTE 10-14 days (THE EDGE)
3. **Trend** - Price above/below EMA-20
4. **Entry** - RSI not extreme (<70 for calls, >30 for puts)
5. **Valuation** - IV percentile < 80

### Exit Logic (Dynamic Trailing)
1. **Time Exit** - Close all at DTE ≤ 4 (priority)
2. **IV Crush** - Exit if IV drops >10%
3. **Stop Loss** - Hard stop at -30%
4. **Momentum Reversal** - Early exit if momentum reverses + 15% loss
5. **Profit Taking** - At +75%, exit 50%, trail remaining with EMA/ATR

### Risk Management (Grok's Reality Checks)
- **Base Position Size**: 35% capital
- **High Confidence**: 45% capital
- **Friday Limit**: 30% max (weekend gap risk)
- **Event Limit**: 20% max (before major events)
- **Realistic Costs**: 7.5% slippage, ₹20 brokerage, 15% tax

---

## 🚀 Quick Start

### Prerequisites
- Python 3.10+
- Zerodha Kite API credentials
- Telegram bot token (optional but recommended)

### Installation

```bash
# Clone or download the bot
cd bot/

# Install dependencies
pip install -r requirements_bot3.txt

# Configure environment
cp .env_bot3.example .env
# Edit .env with your credentials
```

### Configuration

Edit `config_bot3.yaml`:

```yaml
capital: 100000  # Your capital in INR
execution:
  broker: "paper"  # Start with paper trading
  dry_run: true

telegram:
  override_mode: "CONFIRM"  # Require manual confirmation
```

### Run Bot

```bash
python main_bot3.py
```

---

## 📁 Project Structure

```
bot/
├── momentum_bot/
│   ├── core/                # Configuration and constants
│   │   ├── config.py
│   │   └── constants.py
│   ├── data/                # Market data and indicators
│   │   ├── market_data.py
│   │   └── indicators.py
│   ├── signals/             # Signal generation
│   │   ├── regime_classifier.py  # CRITICAL
│   │   ├── momentum_detector.py
│   │   └── confidence_scorer.py
│   ├── portfolio/           # Portfolio management
│   │   └── master_controller.py  # CRITICAL
│   ├── strategy/            # Trading logic
│   │   ├── risk_manager.py
│   │   ├── position_manager.py  # NO ROLLING
│   │   └── exit_handler.py
│   ├── execution/           # Broker interface
│   │   └── broker_interface.py
│   └── monitoring/          # Logging and alerts
│       ├── telegram_bot.py
│       └── logger.py
├── config_bot3.yaml         # Configuration file
├── main_bot3.py             # Main orchestrator
├── requirements_bot3.txt    # Dependencies
└── README_BOT3.md           # This file
```

---

## ⚙️ Configuration Parameters

### Capital & Risk
```yaml
capital: 100000                    # Total capital
max_capital_per_trade_base: 0.35   # Base 35%
max_capital_per_trade_max: 0.45    # Max 45% (high confidence)
max_daily_loss: 15000              # Daily loss limit
max_weekly_loss: 30000             # Weekly loss limit
```

### Entry Filters
```yaml
entry:
  dte_min: 10              # Minimum DTE (THE EDGE)
  dte_max: 14              # Maximum DTE
  strike_distance_min: 250 # Min OTM distance
  strike_distance_max: 350 # Max OTM distance
  adx_threshold: 25        # Trend strength
  rsi_max: 70              # Not overbought
  iv_percentile_max: 80    # IV not too high
```

### Exit Rules
```yaml
exit:
  profit_target_pct: 75      # +75% triggers partial exit
  partial_exit_pct: 0.50     # Exit 50% at target
  stop_loss_pct: 0.30        # -30% hard stop
  time_exit_dte: 4           # Exit when DTE ≤ 4
  iv_crush_threshold: 0.10   # Exit if IV drops >10%
```

---

## 🔐 Environment Variables

Create `.env` file:

```bash
# Zerodha Kite API
KITE_API_KEY=your_api_key
KITE_API_SECRET=your_api_secret
KITE_ACCESS_TOKEN=your_access_token

# Telegram Bot
TELEGRAM_BOT_TOKEN=your_bot_token
TELEGRAM_CHAT_ID=your_chat_id

# Mode
TELEGRAM_MODE=CONFIRM  # CONFIRM, AUTO, or MANUAL
```

---

## 🎛️ Telegram Modes

### CONFIRM Mode (Recommended for Start)
- Bot sends trade signal to Telegram
- You manually confirm or reject each trade
- Safest mode for testing

### AUTO Mode
- Fully automated trading
- Bot executes all trades automatically
- Use only after thorough testing

### MANUAL Mode
- Bot only suggests trades
- You manually place orders
- For experienced traders

---

## 📊 Monitoring

### Telegram Alerts
- ✅ Position opened/closed
- 📊 Daily/weekly summaries
- ⚠️ Risk limit warnings
- 🔄 Regime changes

### Log Files
```
logs/
├── trades_YYYYMMDD.jsonl  # Trade journal
└── system_YYYYMMDD.log    # System logs
```

---

## 🧪 Testing & Validation

### Paper Trading (Recommended First)
1. Set `execution.broker = "paper"` and `dry_run = true`
2. Run for 2-4 weeks
3. Validate signal quality and performance
4. Check logs for errors

### Going Live
1. Ensure paper trading results are satisfactory
2. Start with small capital (₹50K-1L)
3. Set `execution.broker = "kite"` and `dry_run = false`
4. Keep `telegram.override_mode = "CONFIRM"` initially
5. Monitor closely for first week

---

## ⚠️ Important Notes

### Critical Validations on Startup
```
✅ FIX #1: Rolling logic DISABLED
✅ FIX #2: Master Portfolio Controller active
```
If either validation fails, bot will exit immediately.

### Risk Disclaimers
- **This is experimental software** - use at your own risk
- **Start with paper trading** - validate before live
- **Options trading is risky** - you can lose your entire capital
- **No guarantees** - past performance doesn't predict future results

### Realistic Expectations
- **Target**: 50-100% annual return (NOT 360%)
- **Win Rate**: 30-40% (momentum trades have lower win rate but higher R:R)
- **Max Drawdown**: 15-20% expected
- **Trade Frequency**: 2-3 trades per week

---

## 🔧 Troubleshooting

### Bot Not Starting
```bash
# Check Python version
python --version  # Should be 3.10+

# Check dependencies
pip install -r requirements_bot3.txt

# Check configuration
python -c "from momentum_bot.core.config import Config; c = Config(); print(c.capital)"
```

### No Trades Being Taken
- Check market regime (might not be TRENDING)
- Check confidence scores (minimum 70 required)
- Check risk limits (daily/weekly losses)
- Review logs for detailed reasons

### Telegram Not Working
- Verify `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID`
- Test: Send message directly via Telegram API
- Check bot has permissions to send messages

---

## 📈 Performance Tracking

### Metrics to Monitor
1. **Win Rate** - Should be 30-40%
2. **Average R:R** - Should be 2:1 or better
3. **Max Drawdown** - Track largest loss streak
4. **Slippage** - Compare actual vs expected costs
5. **Regime Accuracy** - Check regime classification correctness

### Trade Journal Analysis
```bash
# View trades
cat logs/trades_20250128.jsonl | jq

# Calculate win rate
grep '"event":"EXIT"' logs/trades_*.jsonl | jq -s '[.[] | select(.pnl > 0)] | length'
```

---

## 🚢 Deployment (Railway)

### Option 1: Manual Deployment
```bash
# Build Docker image
docker build -f Dockerfile_bot3 -t mch-bot-3 .

# Run locally
docker run --env-file .env mch-bot-3
```

### Option 2: Railway Deployment
1. Push code to GitHub
2. Connect Railway to repository
3. Set environment variables in Railway dashboard
4. Deploy automatically on push

---

## 📚 Additional Resources

### Documentation
- [Gemini Strategic Analysis](Gemini_Strategic_Analysis.md)
- [Quick Reference Guide](Quick_Reference_Nandi_Upgrades.md)
- [Bot 2.0 vs Bot 3.0 Comparison](MCH_Bot2_Nandi_Upgrades.md)

### Support
- Create an issue on GitHub
- Check logs for detailed error messages
- Review configuration against this README

---

## 📜 License

Proprietary - For personal use only

---

## 🙏 Acknowledgments

**Strategy Development:**
- Dr. Laxman M M (Architect)
- Gemini AI (Strategic Analysis & Critical Fixes)
- Grok AI (Reality Checks & Risk Management)
- Deepseek AI (Asymmetric Sizing)
- Claude AI (Implementation)

**Key Insights:**
- **Gemini**: Identified critical flaw in rolling logic and regime-based conflicts
- **Grok**: Added realistic slippage, gap risk management
- **Deepseek**: Enhanced confidence scoring and position sizing

---

**Last Updated:** January 2025
**Version:** 3.0.0
**Status:** Beta - Paper Trading Recommended
