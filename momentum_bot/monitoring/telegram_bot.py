"""
Telegram Bot for MCH Bot 3.0

Provides:
- Real-time alerts and notifications
- CONFIRM mode for manual trade approval
- Position status updates
- Performance summaries
"""

from typing import Dict, Optional
import logging
import asyncio
from datetime import datetime
import requests


class TelegramBot:
    """
    Telegram bot for notifications and trade confirmations

    Modes:
    - CONFIRM: Require manual confirmation for each trade
    - AUTO: Fully automated (notify only)
    - MANUAL: All trades manual (bot suggests only)
    """

    def __init__(self, config):
        """
        Initialize Telegram bot

        Args:
            config: Config object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.bot_token = config.telegram_bot_token
        self.chat_id = config.telegram_chat_id
        self.mode = config.telegram_override_mode

        # Initialize bot if credentials provided
        if self.bot_token and self.chat_id:
            self._init_bot()
        else:
            self.bot = None
            self.logger.warning("Telegram credentials not configured - notifications disabled")

        self.logger.info(f"TelegramBot initialized: Mode={self.mode}")

    def _init_bot(self):
        """Initialize Telegram bot"""
        try:
            # Test connection with a simple API call
            url = f"https://api.telegram.org/bot{self.bot_token}/getMe"
            response = requests.get(url, timeout=10)

            if response.status_code == 200:
                bot_info = response.json()
                if bot_info.get('ok'):
                    self.logger.info(f"Telegram bot initialized: @{bot_info['result'].get('username')}")
                    self.bot = True  # Mark as initialized
                else:
                    self.logger.error(f"Telegram bot error: {bot_info}")
                    self.bot = None
            else:
                self.logger.error(f"Telegram API error: {response.status_code}")
                self.bot = None

        except Exception as e:
            self.logger.error(f"Failed to initialize Telegram bot: {e}")
            self.bot = None

    async def send_message(self, message: str, parse_mode: str = 'Markdown'):
        """
        Send message to Telegram

        Args:
            message: Message text
            parse_mode: Parse mode ('Markdown' or 'HTML')

        Returns:
            Success status
        """
        if self.bot is None:
            self.logger.debug(f"[Telegram disabled] {message}")
            return False

        try:
            # Use requests instead of python-telegram-bot for simpler async handling
            url = f"https://api.telegram.org/bot{self.bot_token}/sendMessage"

            payload = {
                'chat_id': self.chat_id,
                'text': message,
                'parse_mode': parse_mode
            }

            # Run in executor to avoid blocking
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: requests.post(url, json=payload, timeout=10)
            )

            if response.status_code == 200:
                result = response.json()
                if result.get('ok'):
                    self.logger.debug("Telegram message sent successfully")
                    return True
                else:
                    self.logger.error(f"Telegram API error: {result}")
                    return False
            else:
                self.logger.error(f"Telegram HTTP error: {response.status_code}")
                return False

        except Exception as e:
            self.logger.error(f"Failed to send Telegram message: {e}")
            return False

    async def send_alert(self, alert_type: str, message: str):
        """
        Send alert with emoji and formatting

        Args:
            alert_type: Alert type (entry, exit, error, etc.)
            message: Alert message
        """
        # Quick return if Telegram not configured
        if self.bot is None:
            self.logger.debug(f"[Telegram disabled] {alert_type}: {message}")
            return

        emojis = {
            'entry': '📈',
            'exit': '💰',
            'error': '⚠️',
            'regime_change': '🔄',
            'stop_loss': '🛑',
            'profit': '✅',
            'startup': '🚀',
            'shutdown': '⏹️'
        }

        emoji = emojis.get(alert_type, '📊')
        formatted_message = f"{emoji} *{alert_type.upper()}*\n\n{message}"

        await self.send_message(formatted_message)

    async def request_confirmation(self, signal_data: Dict) -> bool:
        """
        Request manual confirmation for trade (CONFIRM mode)

        Args:
            signal_data: Signal data dict

        Returns:
            True if confirmed, False if rejected/timeout
        """
        if self.mode != 'CONFIRM':
            # In AUTO or MANUAL mode, no confirmation needed
            return self.mode == 'AUTO'

        # If Telegram not configured, return False (reject trade)
        if self.bot is None:
            self.logger.warning("Telegram not configured - rejecting trade (CONFIRM mode requires Telegram)")
            return False

        # Format confirmation request
        message = self._format_confirmation_request(signal_data)

        await self.send_message(message)

        # Wait for user response (simplified - in production use callback buttons)
        self.logger.info("⏳ Waiting for manual confirmation...")

        # For now, auto-approve after 60 seconds (timeout)
        # In production, implement proper callback handling
        await asyncio.sleep(60)

        self.logger.warning("⏰ Confirmation timeout - auto-rejecting")
        return False

    def _format_confirmation_request(self, signal_data: Dict) -> str:
        """
        Format trade confirmation request

        Args:
            signal_data: Signal data

        Returns:
            Formatted message
        """
        direction = signal_data['direction']
        spot = signal_data['spot']
        confidence = signal_data['confidence']

        message = f"""
🔔 *TRADE CONFIRMATION REQUIRED*

━━━━━━━━━━━━━━━━━━━━━━━━━━━
📊 **Signal Details**
Direction: {direction}
Spot: ₹{spot:,.0f}
Confidence: {confidence:.0f}/100

⏰ Timestamp: {signal_data['timestamp'].strftime('%H:%M:%S')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
Reply with:
✅ /confirm - Execute trade
❌ /reject - Skip trade

⏳ Auto-reject in 60 seconds
"""
        return message

    async def send_position_opened(self, position: Dict, order_result: Dict):
        """
        Notify position opened

        Args:
            position: Position dict
            order_result: Order result dict
        """
        message = f"""
📈 *POSITION OPENED*

━━━━━━━━━━━━━━━━━━━━━━━━━━━
**{position['instrument']} {position['strike']} {position['option_type']}**

Quantity: {position['quantity']} ({position['lots']} lots)
Entry: ₹{position['entry_premium']:.2f}
DTE: {position['dte']} days
Confidence: {position['confidence']:.0f}/100

Stop Loss: ₹{position['stop_loss']:.2f}
Target: +75% (₹{position['entry_premium'] * 1.75:.2f})

Mode: {order_result.get('mode', 'UNKNOWN')}
Order ID: {order_result.get('order_id', 'N/A')}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        await self.send_alert('entry', message)

    async def send_position_closed(
        self,
        position: Dict,
        exit_result: Dict,
        reason: str
    ):
        """
        Notify position closed

        Args:
            position: Position dict
            exit_result: Exit result dict
            reason: Exit reason
        """
        pnl = exit_result.get('pnl', 0)
        return_pct = exit_result.get('return_pct', 0)

        pnl_emoji = '✅' if pnl > 0 else '❌'

        message = f"""
{pnl_emoji} *POSITION CLOSED*

━━━━━━━━━━━━━━━━━━━━━━━━━━━
**{position['instrument']} {position['strike']} {position['option_type']}**

Entry: ₹{position['entry_premium']:.2f}
Exit: ₹{exit_result.get('exit_premium', 0):.2f}
Quantity: {exit_result.get('exit_quantity', 0)}

**P&L: ₹{pnl:,.0f}** ({return_pct:+.1f}%)

Hold Time: {self._calculate_hold_time(position)}
Reason: {reason}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        alert_type = 'profit' if pnl > 0 else 'stop_loss'
        await self.send_alert(alert_type, message)

    async def send_daily_summary(self, summary: Dict):
        """
        Send daily performance summary

        Args:
            summary: Summary dict containing:
                - trades: Number of trades
                - winners: Number of winning trades
                - losers: Number of losing trades
                - total_pnl: Total P&L
                - win_rate: Win rate percentage
        """
        message = f"""
📊 *DAILY SUMMARY*

━━━━━━━━━━━━━━━━━━━━━━━━━━━
Trades: {summary.get('trades', 0)}
Winners: {summary.get('winners', 0)} ✅
Losers: {summary.get('losers', 0)} ❌

Win Rate: {summary.get('win_rate', 0):.1f}%

**Total P&L: ₹{summary.get('total_pnl', 0):,.0f}**

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        await self.send_message(message)

    async def send_regime_change(self, old_regime: str, new_regime: str, reason: str):
        """
        Notify regime change

        Args:
            old_regime: Old regime
            new_regime: New regime
            reason: Change reason
        """
        message = f"""
🔄 *REGIME CHANGE*

━━━━━━━━━━━━━━━━━━━━━━━━━━━
{old_regime or 'None'} ➜ **{new_regime}**

{reason}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        await self.send_alert('regime_change', message)

    async def send_risk_alert(self, alert_type: str, message: str):
        """
        Send risk management alert

        Args:
            alert_type: Alert type
            message: Alert message
        """
        formatted = f"""
🛑 *RISK ALERT: {alert_type.upper()}*

━━━━━━━━━━━━━━━━━━━━━━━━━━━
{message}

━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        await self.send_alert('error', formatted)

    async def send_status_update(self, status: Dict):
        """
        Send bot status update

        Args:
            status: Status dict
        """
        message = f"""
📊 *BOT STATUS*

━━━━━━━━━━━━━━━━━━━━━━━━━━━
**Regime:** {status.get('regime', 'Unknown')}
**Active Bot:** {status.get('active_bot', 'None')}

**Positions:** {status.get('active_positions', 0)}/{status.get('max_positions', 2)}
**Available Capital:** ₹{status.get('available_capital', 0):,.0f}

**Daily Loss:** ₹{status.get('daily_loss', 0):,.0f}/{status.get('daily_limit', 0):,}
**Weekly Loss:** ₹{status.get('weekly_loss', 0):,.0f}/{status.get('weekly_limit', 0):,}

Mode: {self.mode}
━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        await self.send_message(message)

    def _calculate_hold_time(self, position: Dict) -> str:
        """
        Calculate position hold time

        Args:
            position: Position dict

        Returns:
            Formatted hold time string
        """
        entry_time = position.get('entry_time', datetime.now())
        exit_time = position.get('exit_time', datetime.now())

        delta = exit_time - entry_time

        hours = delta.seconds // 3600
        minutes = (delta.seconds % 3600) // 60

        if delta.days > 0:
            return f"{delta.days}d {hours}h {minutes}m"
        elif hours > 0:
            return f"{hours}h {minutes}m"
        else:
            return f"{minutes}m"
