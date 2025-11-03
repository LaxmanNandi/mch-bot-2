"""
MCH Bot 3.0 - Momentum Premium Buyer
Main Orchestrator

Integrates all modules and runs the trading loop with:
- CRITICAL: Master Portfolio Controller (Gemini Fix #2)
- CRITICAL: NO Rolling Logic (Gemini Fix #1)
- 5-Factor Momentum Detection
- Dynamic Trailing Exits
- Risk Management with Gap Risk
"""

import asyncio
from typing import Dict
import logging
from datetime import datetime
import sys
import io
from pathlib import Path

# Fix encoding for Windows console
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8', errors='replace')
sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8', errors='replace')

# Add momentum_bot to path
sys.path.insert(0, str(Path(__file__).parent))

from momentum_bot.core.config import Config
from momentum_bot.data.market_data import MarketDataFeed
from momentum_bot.signals.regime_classifier import RegimeClassifier
from momentum_bot.signals.momentum_detector import MomentumDetector
from momentum_bot.signals.confidence_scorer import ConfidenceScorer
from momentum_bot.portfolio.master_controller import MasterPortfolioController
from momentum_bot.strategy.position_manager import PositionManager
from momentum_bot.strategy.risk_manager import RiskManager
from momentum_bot.strategy.exit_handler import ExitHandler
from momentum_bot.execution.broker_interface import BrokerInterface
from momentum_bot.monitoring.telegram_bot import TelegramBot
from momentum_bot.monitoring.logger import TradeLogger


class MomentumBot:
    """
    MCH Bot 3.0 - Momentum Premium Buyer

    Implements Gemini-validated strategy with critical fixes:
    1. NO rolling logic (Gemini Fix #1)
    2. Master portfolio controller to prevent Bot 2/3 conflicts (Gemini Fix #2)
    3. Simplified 5-factor entry model
    4. Dynamic trailing exits
    5. Weekend/event gap risk management
    """

    def __init__(self, config_path: str = None):
        """
        Initialize Momentum Bot

        Args:
            config_path: Path to config file (default: config_bot3.yaml)
        """
        print("=" * 80)
        print("MCH BOT 3.0 - MOMENTUM PREMIUM BUYER")
        print("=" * 80)
        print()

        # Load configuration
        self.config = Config(config_path)
        self.trade_logger = TradeLogger(self.config)
        self.logger = logging.getLogger(__name__)

        # Initialize components
        self.logger.info("Initializing components...")

        # Data feed
        self.market_data = MarketDataFeed(self.config)

        # Signal generation
        self.regime_classifier = RegimeClassifier(self.config)
        self.momentum_detector = MomentumDetector(self.config)
        self.confidence_scorer = ConfidenceScorer(self.config)

        # CRITICAL: Master portfolio controller
        self.master_controller = MasterPortfolioController(
            self.regime_classifier,
            self.logger
        )

        # Strategy components
        self.risk_manager = RiskManager(self.config)
        self.position_manager = PositionManager(self.config, self.risk_manager)
        self.exit_handler = ExitHandler(self.config)

        # Execution & monitoring
        self.broker = BrokerInterface(self.config)
        self.telegram = TelegramBot(self.config)

        # State
        self.running = False

        self.logger.info("✅ MCH Bot 3.0 initialized successfully")
        self.logger.info(f"Mode: {self.config.telegram_override_mode}")
        self.logger.info(f"Broker: {self.config.execution_broker}")
        self.logger.info(f"Dry Run: {self.config.execution_dry_run}")

        # Print critical validations
        self._print_critical_validations()

    def _print_critical_validations(self):
        """Print critical validation checks"""
        print()
        print("=" * 80)
        print("CRITICAL VALIDATIONS (Gemini Fixes)")
        print("=" * 80)

        # Fix #1: NO Rolling
        if not self.config.is_rolling_enabled():
            print("✅ FIX #1: Rolling logic DISABLED")
        else:
            print("❌ ERROR: Rolling logic is enabled! (Violation of Gemini Fix #1)")
            sys.exit(1)

        # Fix #2: Master Controller
        print("✅ FIX #2: Master Portfolio Controller active")

        print("=" * 80)
        print()

    async def run(self):
        """
        Main trading loop
        """
        self.running = True

        self.logger.info("🚀 Starting MCH Bot 3.0...")
        self.logger.info("Sending startup alert...")
        await self.telegram.send_alert('startup', 'MCH Bot 3.0 started')
        self.logger.info("Startup alert sent")

        # Send initial status
        self.logger.info("Sending initial status update...")
        await self._send_status_update()
        self.logger.info("Initial status update sent")

        while self.running:
            try:
                # Check if market is open
                if not self.market_data.is_market_open():
                    self.logger.debug("Market closed - sleeping")
                    await asyncio.sleep(60)
                    continue

                # Fetch latest market data
                self.logger.debug("Fetching market data...")
                data = await self.market_data.get_latest()

                # CRITICAL: Check with master controller
                can_trade, reason = self.master_controller.should_bot_3_trade(data)

                if not can_trade:
                    self.logger.debug(f"Bot 3 inactive: {reason}")
                    await asyncio.sleep(60)
                    continue

                # Check existing positions for exits
                await self.check_exits(data)

                # Check for new entry signals
                await self.check_entries(data)

                # Sleep until next check (1 minute)
                await asyncio.sleep(60)

            except KeyboardInterrupt:
                self.logger.info("Received shutdown signal")
                break
            except Exception as e:
                self.logger.error(f"Error in main loop: {e}", exc_info=True)
                await self.telegram.send_alert('error', f"Bot error: {e}")
                await asyncio.sleep(60)

        await self.shutdown()

    async def check_entries(self, data: Dict):
        """
        Check for entry signals and execute if conditions met

        Args:
            data: Market data dict
        """
        # Check risk limits
        should_close, reason = self.risk_manager.should_close_all_positions()
        if should_close:
            self.logger.warning(f"⚠️ Risk limit triggered: {reason}")
            await self.telegram.send_risk_alert('LIMIT_EXCEEDED', reason)
            return

        # Get risk status
        risk_status = self.risk_manager.get_risk_status()
        if not risk_status['can_take_position']:
            self.logger.debug("Cannot take new position (risk limits)")
            return

        # Detect momentum (Gemini's 5-factor model)
        bullish, factors = self.momentum_detector.detect_bullish_momentum(data)
        bearish, _ = self.momentum_detector.detect_bearish_momentum(data)

        if not (bullish or bearish):
            self.logger.debug("No momentum signal detected")
            return

        direction = 'CALL' if bullish else 'PUT'

        # Calculate confidence (0-100 scoring)
        regime_confidence = self.regime_classifier.get_regime_confidence(data)
        confidence = self.confidence_scorer.calculate(data, factors, regime_confidence)

        # Check minimum confidence threshold
        should_trade, conf_reason = self.confidence_scorer.should_take_trade(confidence)
        if not should_trade:
            self.logger.info(f"❌ Trade rejected: {conf_reason}")
            return

        # Prepare signal data
        signal_data = {
            'direction': direction,
            'spot': data['spot'],
            'confidence': confidence,
            'iv_percentile': data['iv_percentile'],
            'timestamp': data['timestamp']
        }

        self.logger.info(
            f"✓ Signal detected: {direction} | "
            f"Spot={data['spot']:.0f} | "
            f"Confidence={confidence:.0f}/100"
        )

        # Telegram confirmation (if in CONFIRM mode)
        if self.config.telegram_override_mode == 'CONFIRM':
            approved = await self.telegram.request_confirmation(signal_data)
            if not approved:
                self.logger.info("Trade rejected by user")
                return

        # Create position
        position = self.position_manager.enter_position(
            signal_data,
            confidence,
            data
        )

        if position is None:
            self.logger.warning("Position creation failed (risk validation)")
            return

        # Execute order
        order_result = await self.broker.place_order(position)

        if order_result.get('success'):
            self.logger.info(f"✅ Position opened: {position['position_id']}")

            # Log and notify
            self.trade_logger.log_entry(position, order_result)
            await self.telegram.send_position_opened(position, order_result)
        else:
            self.logger.error(f"Order placement failed: {order_result.get('error')}")
            await self.telegram.send_alert('error', f"Order failed: {order_result.get('error')}")

    async def check_exits(self, data: Dict):
        """
        Check all active positions for exit signals

        Args:
            data: Market data dict
        """
        active_positions = self.position_manager.get_active_positions()

        for position in active_positions:
            try:
                # Get current option premium
                current_premium = await self.market_data.get_option_premium(
                    position['strike'],
                    position['expiry_str'],
                    position['option_type']
                )

                # Update position P&L
                self.position_manager.update_position_pnl(position, current_premium)

                # Update data with current premium
                exit_data = {**data, 'premium': current_premium}

                # Check exit conditions
                exit_signal = self.exit_handler.check_exits(position, exit_data)

                if exit_signal['action'] != 'HOLD':
                    self.logger.info(
                        f"Exit signal: {position['position_id']} | "
                        f"Action={exit_signal['action']} | "
                        f"Reason={exit_signal['reason']}"
                    )

                    # Execute exit
                    if exit_signal['action'] == 'PARTIAL_EXIT':
                        exit_quantity = int(position['remaining_quantity'] * exit_signal['percentage'])
                    else:
                        exit_quantity = position['remaining_quantity']

                    # Place exit order
                    close_result = await self.broker.close_position(
                        position,
                        exit_quantity,
                        current_premium
                    )

                    if close_result.get('success'):
                        # Update position manager
                        result = self.position_manager.exit_position(
                            position,
                            exit_signal,
                            current_premium
                        )

                        # Log and notify
                        self.trade_logger.log_exit(position, result, exit_signal['reason'])
                        await self.telegram.send_position_closed(
                            position,
                            result,
                            exit_signal['reason']
                        )

                        self.logger.info(
                            f"✅ Position closed: {position['position_id']} | "
                            f"P&L: ₹{result['pnl']:,.0f}"
                        )

            except Exception as e:
                self.logger.error(f"Error checking exit for {position['position_id']}: {e}")

    async def _send_status_update(self):
        """Send status update to Telegram"""
        try:
            # Skip if telegram not configured
            if self.telegram.bot is None:
                self.logger.debug("Telegram not configured - skipping status update")
                return

            self.logger.debug("Getting risk status...")
            risk_status = self.risk_manager.get_risk_status()
            self.logger.debug("Getting regime...")
            regime = self.master_controller.get_current_regime()
            self.logger.debug("Getting active bot...")
            active_bot = self.master_controller.get_active_bot_name()

            status = {
                'regime': regime.value if regime else 'Initializing',
                'active_bot': active_bot,
                'active_positions': risk_status['active_positions'],
                'max_positions': risk_status['max_positions'],
                'available_capital': risk_status['available_capital'],
                'daily_loss': risk_status['daily_loss'],
                'daily_limit': risk_status['daily_limit'],
                'weekly_loss': risk_status['weekly_loss'],
                'weekly_limit': risk_status['weekly_limit']
            }

            self.logger.debug("Sending status to Telegram...")
            await self.telegram.send_status_update(status)
            self.logger.debug("Status update complete")
        except Exception as e:
            self.logger.error(f"Error sending status update: {e}", exc_info=True)

    async def shutdown(self):
        """Graceful shutdown"""
        self.logger.info("Shutting down MCH Bot 3.0...")

        self.running = False

        # Send final status
        await self._send_status_update()
        await self.telegram.send_alert('shutdown', 'MCH Bot 3.0 stopped')

        self.logger.info("✅ Shutdown complete")


async def main():
    """Main entry point"""
    bot = MomentumBot()

    try:
        await bot.run()
    except KeyboardInterrupt:
        print("\nShutdown requested by user")
    except Exception as e:
        logging.error(f"Fatal error: {e}", exc_info=True)
    finally:
        print("Bot stopped")


if __name__ == "__main__":
    asyncio.run(main())
