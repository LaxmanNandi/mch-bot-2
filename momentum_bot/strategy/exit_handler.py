"""
Exit Handler for MCH Bot 3.0

Implements Gemini's Dynamic Exit Strategy:
- Multi-layered exit logic with priorities
- Dynamic trailing stops (EMA or ATR based)
- Time-based exits (DTE and Wednesday rule)
- IV crush detection
- Momentum reversal detection
"""

from typing import Dict
from datetime import datetime, time
import logging


class ExitHandler:
    """
    Dynamic exit handler with trailing stops

    Exit Priority:
    1. Time-based (DTE ≤ 4, Wednesday 2 PM)
    2. IV crush detection
    3. Stop loss (-30%)
    4. Momentum reversal + loss
    5. Dynamic profit taking (75% target with trailing)
    """

    def __init__(self, config):
        """
        Initialize exit handler

        Args:
            config: Config object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Exit parameters
        self.profit_target = config.exit_profit_target_pct / 100  # 0.75
        self.partial_exit_pct = config.exit_partial_exit_pct  # 0.50
        self.stop_loss_pct = config.exit_stop_loss_pct  # 0.30
        self.time_exit_dte = config.exit_time_exit_dte  # 4
        self.iv_crush_threshold = config.exit_iv_crush_threshold  # 0.10
        self.trailing_method = config.exit_trailing_method  # "ema_20" or "atr_1.5"
        self.wednesday_exit = config.exit_wednesday_exit

        self.logger.info(
            f"ExitHandler initialized: "
            f"Target={self.profit_target:.0%}, "
            f"SL={self.stop_loss_pct:.0%}, "
            f"DTE={self.time_exit_dte}, "
            f"Trailing={self.trailing_method}"
        )

    def check_exits(self, position: Dict, current_data: Dict) -> Dict:
        """
        Multi-layered exit logic

        Args:
            position: Position dict
            current_data: Current market data containing:
                - premium: Current option premium
                - spot: Current spot price
                - ema_20: 20-period EMA
                - atr: Current ATR
                - iv_percentile: Current IV percentile
                - adx: Current ADX
                - di_plus: DI+
                - di_minus: DI-

        Returns:
            Exit signal dict with action and reason
        """
        # Calculate current DTE
        dte = self._days_to_expiry(position['expiry_date'])

        # PRIORITY 1: Time-based exit (CRITICAL - THE EDGE)
        if dte <= self.time_exit_dte:
            return {
                'action': 'EXIT_ALL',
                'reason': f'Time exit: {dte} DTE ≤ {self.time_exit_dte}',
                'priority': 'CRITICAL'
            }

        # Wednesday 2 PM rule
        if self.wednesday_exit and self._is_wednesday_after_2pm():
            days_held = (datetime.now() - position['entry_time']).days
            if days_held <= 2:
                return {
                    'action': 'EXIT_ALL',
                    'reason': 'Wednesday 2pm rule (opened this week)',
                    'priority': 'HIGH'
                }

        # PRIORITY 2: IV Crush detection (GROK addition)
        iv_drop = self._calculate_iv_drop(position, current_data)
        if iv_drop > self.iv_crush_threshold:
            return {
                'action': 'EXIT_ALL',
                'reason': f'IV crush: {iv_drop*100:.1f}% drop',
                'priority': 'HIGH'
            }

        # PRIORITY 3: Stop loss
        loss_pct = self._calculate_loss_pct(position, current_data)
        if loss_pct >= self.stop_loss_pct:
            return {
                'action': 'EXIT_ALL',
                'reason': f'Stop loss: -{loss_pct*100:.1f}%',
                'priority': 'URGENT'
            }

        # PRIORITY 4: Momentum reversal (early exit for losers)
        if loss_pct > 0.15 and self._momentum_reversed(position, current_data):
            return {
                'action': 'EXIT_ALL',
                'reason': 'Momentum reversal + 15% loss',
                'priority': 'MEDIUM'
            }

        # PRIORITY 5: Dynamic profit taking (GEMINI'S ENHANCEMENT)
        profit_pct = self._calculate_profit_pct(position, current_data)

        if profit_pct >= self.profit_target:  # 75% profit

            if not position.get('partial_exit_done', False):
                # First time hitting target - partial exit
                return {
                    'action': 'PARTIAL_EXIT',
                    'percentage': self.partial_exit_pct,  # Exit 50%
                    'reason': f'Profit target: +{profit_pct*100:.1f}%',
                    'next_action': 'MOVE_STOP_TO_BREAKEVEN',
                    'priority': 'PROFIT'
                }

            else:
                # Already did partial exit, now trailing
                trailing_stop = self._calculate_trailing_stop(
                    position,
                    current_data,
                    method=self.trailing_method
                )

                if current_data['premium'] <= trailing_stop:
                    return {
                        'action': 'EXIT_ALL',
                        'reason': f'Trailing stop hit: {trailing_stop:.2f}',
                        'profit_locked': profit_pct,
                        'priority': 'PROFIT'
                    }

        return {'action': 'HOLD', 'reason': 'All conditions green', 'priority': 'NONE'}

    def _days_to_expiry(self, expiry_date) -> int:
        """
        Calculate days to expiry

        Args:
            expiry_date: Expiry date

        Returns:
            Days remaining
        """
        if isinstance(expiry_date, str):
            expiry_date = datetime.strptime(expiry_date, '%Y-%m-%d').date()

        today = datetime.now().date()
        delta = expiry_date - today

        return max(0, delta.days)

    def _is_wednesday_after_2pm(self) -> bool:
        """
        Check if it's Wednesday after 2 PM

        Returns:
            True if Wednesday after 2 PM
        """
        now = datetime.now()

        if now.weekday() != 2:  # Wednesday = 2
            return False

        cutoff_time = time(14, 0)  # 2:00 PM

        return now.time() >= cutoff_time

    def _calculate_iv_drop(self, position: Dict, current_data: Dict) -> float:
        """
        Calculate IV drop since entry

        Args:
            position: Position dict
            current_data: Current market data

        Returns:
            IV drop as decimal (0.10 = 10% drop)
        """
        entry_iv = position.get('entry_iv', 50)
        current_iv = current_data.get('iv_percentile', 50)

        iv_drop = (entry_iv - current_iv) / 100

        return max(0, iv_drop)

    def _calculate_loss_pct(self, position: Dict, current_data: Dict) -> float:
        """
        Calculate current loss percentage

        Args:
            position: Position dict
            current_data: Current market data

        Returns:
            Loss percentage as decimal (0.30 = 30% loss)
        """
        entry_premium = position['entry_premium']
        current_premium = current_data['premium']

        if current_premium >= entry_premium:
            return 0.0  # Not a loss

        loss_pct = (entry_premium - current_premium) / entry_premium

        return loss_pct

    def _calculate_profit_pct(self, position: Dict, current_data: Dict) -> float:
        """
        Calculate current profit percentage

        Args:
            position: Position dict
            current_data: Current market data

        Returns:
            Profit percentage as decimal (0.75 = 75% profit)
        """
        entry_premium = position['entry_premium']
        current_premium = current_data['premium']

        if current_premium <= entry_premium:
            return 0.0  # Not a profit

        profit_pct = (current_premium - entry_premium) / entry_premium

        return profit_pct

    def _momentum_reversed(self, position: Dict, current_data: Dict) -> bool:
        """
        Check if momentum has reversed

        Args:
            position: Position dict
            current_data: Current market data

        Returns:
            True if momentum reversed
        """
        option_type = position['option_type']

        # For CALL options - check if bearish momentum
        if option_type == 'CALL':
            # Bearish signs:
            # 1. Price below EMA
            # 2. DI- > DI+
            # 3. Weakening ADX

            price_below_ema = current_data['spot'] < current_data.get('ema_20', current_data['spot'])
            bearish_direction = current_data.get('di_minus', 0) > current_data.get('di_plus', 0)

            if price_below_ema and bearish_direction:
                self.logger.debug("Momentum reversed (CALL): Price below EMA and bearish DI")
                return True

        # For PUT options - check if bullish momentum
        elif option_type == 'PUT':
            # Bullish signs:
            # 1. Price above EMA
            # 2. DI+ > DI-

            price_above_ema = current_data['spot'] > current_data.get('ema_20', current_data['spot'])
            bullish_direction = current_data.get('di_plus', 0) > current_data.get('di_minus', 0)

            if price_above_ema and bullish_direction:
                self.logger.debug("Momentum reversed (PUT): Price above EMA and bullish DI")
                return True

        return False

    def _calculate_trailing_stop(
        self,
        position: Dict,
        current_data: Dict,
        method: str = 'ema_20'
    ) -> float:
        """
        Calculate trailing stop based on method

        Args:
            position: Position dict
            current_data: Current market data
            method: Trailing method ('ema_20' or 'atr_1.5')

        Returns:
            Trailing stop price
        """
        if method == 'ema_20':
            # Use 20-period EMA as trailing stop
            # For options, translate spot EMA to option premium level

            entry_spot = position['entry_spot']
            current_spot = current_data['spot']
            spot_move_pct = (current_spot - entry_spot) / entry_spot

            # Apply same percentage move to entry premium
            trailing_stop = position['entry_premium'] * (1 + spot_move_pct * 0.5)

            return max(trailing_stop, position['entry_premium'])

        elif method == 'atr_1.5':
            # Use 1.5x ATR below current spot, translate to premium

            atr = current_data.get('atr', 0)
            spot_stop = current_data['spot'] - (1.5 * atr)

            # Estimate premium at spot_stop
            # Simplified: Assume linear relationship
            spot_move = current_data['spot'] - spot_stop
            premium_adjustment = spot_move * 0.05  # Rough delta

            trailing_stop = current_data['premium'] - premium_adjustment

            return max(trailing_stop, position['entry_premium'])

        else:
            # Fallback to entry price
            return position['entry_premium']

    def should_hold_overnight(self, position: Dict, current_data: Dict) -> bool:
        """
        Check if position should be held overnight

        Args:
            position: Position dict
            current_data: Current market data

        Returns:
            True if safe to hold overnight
        """
        # Don't hold if:
        # 1. DTE <= 4 (near expiry)
        # 2. Large unrealized loss (>20%)
        # 3. Major event next day

        dte = self._days_to_expiry(position['expiry_date'])
        if dte <= 4:
            return False

        loss_pct = self._calculate_loss_pct(position, current_data)
        if loss_pct > 0.20:
            return False

        # TODO: Check event calendar

        return True
