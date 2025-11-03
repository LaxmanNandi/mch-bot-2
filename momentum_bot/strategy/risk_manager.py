"""
Risk Manager for MCH Bot 3.0

Multi-tier risk management with:
- Position sizing (asymmetric based on confidence)
- Weekend/event gap risk limits (Grok enhancement)
- Daily/weekly loss limits
- Maximum position count enforcement
"""

from typing import Dict, Tuple, List, Optional
from datetime import datetime, timedelta
import logging


class RiskManager:
    """
    Comprehensive risk management system

    Features:
    - Asymmetric position sizing (35-45% based on confidence)
    - Weekend gap risk (30% max on Fridays)
    - Event risk (20% max before major events)
    - Daily/weekly loss limits
    - Position count limits
    """

    def __init__(self, config):
        """
        Initialize risk manager

        Args:
            config: Config object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Capital and limits
        self.capital = config.capital
        self.max_capital_base = config.max_capital_per_trade_base
        self.max_capital_max = config.max_capital_per_trade_max
        self.max_loss_per_trade = config.max_loss_per_trade
        self.max_daily_loss = config.max_daily_loss
        self.max_weekly_loss = config.max_weekly_loss
        self.max_positions = config.max_positions

        # Grok enhancements
        self.weekend_max = config.risk_weekend_max_capital
        self.event_max = config.risk_event_max_capital

        # Loss tracking
        self.daily_loss = 0.0
        self.weekly_loss = 0.0
        self.current_day = datetime.now().date()
        self.week_start = self._get_week_start()

        # Active positions tracking
        self.active_positions: List[Dict] = []

        self.logger.info(
            f"RiskManager initialized: "
            f"Capital=Rs.{self.capital:,}, "
            f"Base={self.max_capital_base:.0%}, "
            f"Max={self.max_capital_max:.0%}, "
            f"Weekend={self.weekend_max:.0%}, "
            f"Event={self.event_max:.0%}"
        )

    def calculate_position_size(
        self,
        confidence: float,
        market_data: Dict,
        multiplier: float = 1.0
    ) -> float:
        """
        Calculate position size based on confidence and risk factors

        Args:
            confidence: Confidence score (0-100)
            market_data: Market data dict
            multiplier: Optional multiplier from confidence scorer

        Returns:
            Position size in INR
        """
        # Base allocation from confidence
        if confidence >= 85:
            allocation = self.max_capital_max  # 45%
        elif confidence >= 70:
            allocation = 0.40  # 40%
        else:
            allocation = self.max_capital_base  # 35%

        # Apply multiplier
        allocation *= multiplier

        # Gap risk adjustments (GROK)
        day_of_week = datetime.now().weekday()

        # Friday limit (weekend gap risk)
        if day_of_week == 4:  # Friday
            allocation = min(allocation, self.weekend_max)
            self.logger.info(
                f"Friday position sizing: Limited to {self.weekend_max:.0%} (weekend gap risk)"
            )

        # Event risk check
        if self._is_major_event_pending():
            allocation = min(allocation, self.event_max)
            self.logger.warning(
                f"Major event pending: Limited to {self.event_max:.0%}"
            )

        # Calculate position value
        position_value = self.capital * allocation

        self.logger.debug(
            f"Position sizing: Confidence={confidence:.0f}, "
            f"Allocation={allocation:.1%}, "
            f"Size=Rs.{position_value:,.0f}"
        )

        return position_value

    def validate_entry(self, proposed_position: Dict) -> Tuple[bool, str]:
        """
        Pre-flight validation for new position

        Args:
            proposed_position: Position dict with:
                - quantity: Position quantity
                - entry_premium: Entry price
                - stop_loss: Stop loss price

        Returns:
            (is_valid: bool, reason: str)
        """
        # Reset daily/weekly counters if needed
        self._update_loss_counters()

        # 1. Check daily loss limit
        if self.daily_loss >= self.max_daily_loss:
            return False, f"Daily loss limit hit: Rs.{self.daily_loss:,.0f}"

        # 2. Check weekly loss limit
        if self.weekly_loss >= self.max_weekly_loss:
            return False, f"Weekly loss limit hit: Rs.{self.weekly_loss:,.0f}"

        # 3. Check position count
        active_count = len(self.active_positions)
        if active_count >= self.max_positions:
            return False, f"Max positions reached: {active_count}/{self.max_positions}"

        # 4. Validate position risk
        position_risk = self._calculate_position_risk(proposed_position)
        if position_risk > self.max_loss_per_trade:
            return False, f"Position risk too high: Rs.{position_risk:,.0f} > Rs.{self.max_loss_per_trade:,}"

        # 5. Check if position would exceed capital
        position_value = proposed_position['quantity'] * proposed_position['entry_premium']
        total_exposure = self._calculate_total_exposure() + position_value

        if total_exposure > self.capital:
            return False, f"Insufficient capital: Need Rs.{position_value:,.0f}, Available Rs.{self.capital - self._calculate_total_exposure():,.0f}"

        return True, "Risk checks passed"

    def record_position_entry(self, position: Dict):
        """
        Record new position entry

        Args:
            position: Position dict
        """
        self.active_positions.append(position)
        self.logger.info(
            f"Position added: {len(self.active_positions)}/{self.max_positions} active"
        )

    def record_position_exit(self, position: Dict, pnl: float):
        """
        Record position exit and update loss tracking

        Args:
            position: Position dict
            pnl: Profit/Loss in INR
        """
        # Remove from active positions
        self.active_positions = [p for p in self.active_positions if p != position]

        # Update loss tracking (only track losses)
        if pnl < 0:
            self.daily_loss += abs(pnl)
            self.weekly_loss += abs(pnl)

            self.logger.warning(
                f"Loss recorded: Rs.{pnl:,.0f} | "
                f"Daily: Rs.{self.daily_loss:,.0f}/{self.max_daily_loss:,} | "
                f"Weekly: Rs.{self.weekly_loss:,.0f}/{self.max_weekly_loss:,}"
            )
        else:
            self.logger.info(f"Profit recorded: Rs.{pnl:,.0f}")

    def get_active_positions(self) -> List[Dict]:
        """Get list of active positions"""
        return self.active_positions.copy()

    def get_available_capital(self) -> float:
        """
        Calculate available capital for new positions

        Returns:
            Available capital in INR
        """
        used_capital = self._calculate_total_exposure()
        return max(0, self.capital - used_capital)

    def get_risk_status(self) -> Dict:
        """
        Get current risk status

        Returns:
            Dict with risk metrics
        """
        self._update_loss_counters()

        return {
            'capital': self.capital,
            'available_capital': self.get_available_capital(),
            'used_capital': self._calculate_total_exposure(),
            'daily_loss': self.daily_loss,
            'daily_loss_pct': (self.daily_loss / self.capital) * 100,
            'daily_limit': self.max_daily_loss,
            'daily_limit_used_pct': (self.daily_loss / self.max_daily_loss) * 100,
            'weekly_loss': self.weekly_loss,
            'weekly_loss_pct': (self.weekly_loss / self.capital) * 100,
            'weekly_limit': self.max_weekly_loss,
            'weekly_limit_used_pct': (self.weekly_loss / self.max_weekly_loss) * 100,
            'active_positions': len(self.active_positions),
            'max_positions': self.max_positions,
            'can_take_position': len(self.active_positions) < self.max_positions
                                  and self.daily_loss < self.max_daily_loss
                                  and self.weekly_loss < self.max_weekly_loss
        }

    def _calculate_position_risk(self, position: Dict) -> float:
        """
        Calculate maximum risk for a position

        Args:
            position: Position dict

        Returns:
            Maximum risk in INR
        """
        quantity = position['quantity']
        entry_premium = position['entry_premium']
        stop_loss = position.get('stop_loss', 0)

        # Maximum risk is entry premium to stop loss
        risk_per_unit = entry_premium - stop_loss
        total_risk = quantity * risk_per_unit

        return abs(total_risk)

    def _calculate_total_exposure(self) -> float:
        """
        Calculate total capital deployed in active positions

        Returns:
            Total exposure in INR
        """
        total = 0.0
        for position in self.active_positions:
            total += position['quantity'] * position['entry_premium']
        return total

    def _update_loss_counters(self):
        """Reset daily/weekly loss counters if needed"""
        current_date = datetime.now().date()

        # Reset daily counter
        if current_date != self.current_day:
            self.logger.info(
                f"New trading day: Resetting daily loss from Rs.{self.daily_loss:,.0f}"
            )
            self.daily_loss = 0.0
            self.current_day = current_date

        # Reset weekly counter
        week_start = self._get_week_start()
        if week_start != self.week_start:
            self.logger.info(
                f"New trading week: Resetting weekly loss from Rs.{self.weekly_loss:,.0f}"
            )
            self.weekly_loss = 0.0
            self.week_start = week_start

    def _get_week_start(self) -> datetime.date:
        """Get start of current trading week (Monday)"""
        today = datetime.now().date()
        monday = today - timedelta(days=today.weekday())
        return monday

    def _is_major_event_pending(self) -> bool:
        """
        Check for major events in next 24-48 hours

        Major events:
        - RBI policy meetings
        - Budget day
        - Elections
        - Fed meetings (for India)
        - Major economic data releases

        Returns:
            True if major event pending
        """
        # TODO: Implement event calendar checking
        # For now, check if it's a known event date

        # Placeholder: Check for common event days
        # In production, integrate with economic calendar API

        today = datetime.now().date()

        # Budget day (Feb 1st typically)
        if today.month == 2 and today.day == 1:
            self.logger.warning("Budget Day - Reducing position size")
            return True

        # RBI policy dates (check manually or via API)
        # Fed meeting dates
        # Election days

        return False

    def should_close_all_positions(self) -> Tuple[bool, str]:
        """
        Check if all positions should be closed due to risk limits

        Returns:
            (should_close: bool, reason: str)
        """
        self._update_loss_counters()

        # Daily loss limit hit
        if self.daily_loss >= self.max_daily_loss:
            return True, f"Daily loss limit reached: Rs.{self.daily_loss:,.0f}"

        # Weekly loss limit hit
        if self.weekly_loss >= self.max_weekly_loss:
            return True, f"Weekly loss limit reached: Rs.{self.weekly_loss:,.0f}"

        # 80% of daily limit used (warning)
        if self.daily_loss >= self.max_daily_loss * 0.8:
            self.logger.warning(
                f"⚠️ Daily loss at {(self.daily_loss/self.max_daily_loss)*100:.0f}% of limit"
            )

        return False, "Risk limits OK"

    def get_max_additional_risk(self) -> float:
        """
        Calculate maximum additional risk that can be taken

        Returns:
            Maximum additional risk in INR
        """
        remaining_daily = self.max_daily_loss - self.daily_loss
        remaining_weekly = self.max_weekly_loss - self.weekly_loss

        return min(remaining_daily, remaining_weekly, self.max_loss_per_trade)
