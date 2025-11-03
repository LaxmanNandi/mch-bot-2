"""
Position Manager for MCH Bot 3.0

CRITICAL: NO ROLLING FUNCTIONALITY (Gemini Fix #1)

Manages position entries and exits
Strike selection, expiry selection, quantity calculation
"""

from typing import Dict, Optional, List
from datetime import datetime, timedelta
import logging

from momentum_bot.core.constants import OptionType, PositionStatus
from momentum_bot.strategy.risk_manager import RiskManager


class PositionManager:
    """
    Manages positions for momentum strategy

    CRITICAL NOTE: This manager does NOT support position rolling.
    Rolling logic has been deliberately excluded per Gemini Fix #1.
    Each position is independent and cannot be "rolled" to next expiry.
    """

    def __init__(self, config, risk_manager: RiskManager):
        """
        Initialize position manager

        Args:
            config: Config object
            risk_manager: RiskManager instance
        """
        self.config = config
        self.risk_manager = risk_manager
        self.logger = logging.getLogger(__name__)

        # Position tracking
        self.positions: Dict[str, Dict] = {}
        self.position_counter = 0

        self.logger.info("PositionManager initialized")
        self.logger.info("⚠️  ROLLING DISABLED - Each position is independent (Gemini Fix #1)")

    def enter_position(
        self,
        signal_data: Dict,
        confidence_score: float,
        market_data: Dict
    ) -> Optional[Dict]:
        """
        Create new position entry

        Args:
            signal_data: Signal data containing:
                - direction: 'CALL' or 'PUT'
                - spot: Current spot price
                - iv_percentile: IV percentile
                - timestamp: Signal timestamp
            confidence_score: Confidence score (0-100)
            market_data: Market data dict

        Returns:
            Position dict or None if validation fails
        """
        # Calculate position size
        position_value = self.risk_manager.calculate_position_size(
            confidence=confidence_score,
            market_data=market_data
        )

        # Select strike (250-350 OTM)
        strike = self._select_strike(
            spot=signal_data['spot'],
            direction=signal_data['direction'],
            min_otm=self.config.entry_strike_distance_min,
            max_otm=self.config.entry_strike_distance_max
        )

        # Find optimal expiry (10-14 DTE - THE EDGE)
        expiry_date, expiry_str, dte = self._find_expiry(
            target_dte_min=self.config.entry_dte_min,
            target_dte_max=self.config.entry_dte_max
        )

        # Get option premium (from market data or broker)
        # For now, use simplified calculation
        premium = self._estimate_premium(
            spot=signal_data['spot'],
            strike=strike,
            dte=dte,
            iv_percentile=signal_data['iv_percentile']
        )

        # Calculate quantity
        lot_size = self.config.instrument_lot_size
        lots = int(position_value / (premium * lot_size))
        lots = max(1, lots)  # At least 1 lot
        quantity = lots * lot_size

        # Calculate stop loss (30% below entry)
        stop_loss = premium * (1 - self.config.exit_stop_loss_pct)

        # Create position object
        position_id = self._generate_position_id()

        position = {
            'position_id': position_id,
            'instrument': self.config.instrument_symbol,
            'strike': strike,
            'expiry_date': expiry_date,
            'expiry_str': expiry_str,
            'dte': dte,
            'option_type': signal_data['direction'],
            'quantity': quantity,
            'lots': lots,
            'entry_premium': premium,
            'entry_spot': signal_data['spot'],
            'entry_time': datetime.now(),
            'entry_iv': signal_data['iv_percentile'],
            'confidence': confidence_score,
            'stop_loss': stop_loss,
            'status': PositionStatus.PENDING,

            # Tracking fields
            'partial_exit_done': False,
            'partial_exit_quantity': 0,
            'remaining_quantity': quantity,
            'realized_pnl': 0.0,
            'unrealized_pnl': 0.0,

            # CRITICAL: NO rolling fields (Gemini Fix #1)
            # DO NOT ADD: roll_count, can_roll, roll_trigger, etc.
        }

        # Validate position with risk manager
        is_valid, reason = self.risk_manager.validate_entry(position)

        if not is_valid:
            self.logger.warning(f"Position entry rejected: {reason}")
            return None

        # Record position
        self.positions[position_id] = position
        self.risk_manager.record_position_entry(position)

        self.logger.info(
            f"✓ Position created: {position_id} | "
            f"{quantity} x {self.config.instrument_symbol} "
            f"{strike} {signal_data['direction']} "
            f"@ Rs.{premium:.2f} | "
            f"DTE: {dte} | "
            f"Confidence: {confidence_score:.0f}"
        )

        return position

    def exit_position(
        self,
        position: Dict,
        exit_signal: Dict,
        current_premium: float
    ) -> Dict:
        """
        Exit position (full or partial)

        Args:
            position: Position dict
            exit_signal: Exit signal containing:
                - action: 'EXIT_ALL' or 'PARTIAL_EXIT'
                - percentage: Percentage to exit (for partial)
                - reason: Exit reason
            current_premium: Current option premium

        Returns:
            Exit result dict
        """
        position_id = position['position_id']
        action = exit_signal['action']

        if action == 'PARTIAL_EXIT':
            # Partial exit (typically 50% at profit target)
            exit_pct = exit_signal.get('percentage', 0.50)
            exit_quantity = int(position['remaining_quantity'] * exit_pct)

            # Ensure multiple of lot size
            lot_size = self.config.instrument_lot_size
            exit_quantity = (exit_quantity // lot_size) * lot_size

            if exit_quantity == 0:
                self.logger.warning(f"Partial exit quantity too small, skipping")
                return {'success': False, 'reason': 'Quantity too small'}

            # Calculate P&L for partial exit
            pnl = (current_premium - position['entry_premium']) * exit_quantity

            # Update position
            position['partial_exit_done'] = True
            position['partial_exit_quantity'] += exit_quantity
            position['remaining_quantity'] -= exit_quantity
            position['realized_pnl'] += pnl

            # Move stop to breakeven on remaining
            position['stop_loss'] = position['entry_premium']

            self.logger.info(
                f"✓ Partial exit: {position_id} | "
                f"Exited {exit_quantity}/{position['quantity']} @ Rs.{current_premium:.2f} | "
                f"P&L: Rs.{pnl:,.0f} | "
                f"Reason: {exit_signal['reason']}"
            )

            return {
                'success': True,
                'position_id': position_id,
                'action': 'PARTIAL_EXIT',
                'exit_quantity': exit_quantity,
                'remaining_quantity': position['remaining_quantity'],
                'exit_premium': current_premium,
                'pnl': pnl,
                'reason': exit_signal['reason']
            }

        else:  # EXIT_ALL
            # Full exit
            exit_quantity = position['remaining_quantity']
            pnl = (current_premium - position['entry_premium']) * exit_quantity

            # Update position
            position['status'] = PositionStatus.CLOSED
            position['exit_time'] = datetime.now()
            position['exit_premium'] = current_premium
            position['realized_pnl'] += pnl
            position['remaining_quantity'] = 0

            # Record with risk manager
            total_pnl = position['realized_pnl']
            self.risk_manager.record_position_exit(position, total_pnl)

            # Remove from active positions
            if position_id in self.positions:
                del self.positions[position_id]

            self.logger.info(
                f"✓ Full exit: {position_id} | "
                f"Exited {exit_quantity} @ Rs.{current_premium:.2f} | "
                f"Total P&L: Rs.{total_pnl:,.0f} | "
                f"Return: {(total_pnl / (position['entry_premium'] * position['quantity'])) * 100:.1f}% | "
                f"Reason: {exit_signal['reason']}"
            )

            return {
                'success': True,
                'position_id': position_id,
                'action': 'EXIT_ALL',
                'exit_quantity': exit_quantity,
                'exit_premium': current_premium,
                'pnl': total_pnl,
                'return_pct': (total_pnl / (position['entry_premium'] * position['quantity'])) * 100,
                'reason': exit_signal['reason']
            }

    def get_active_positions(self) -> List[Dict]:
        """Get all active positions"""
        return [p for p in self.positions.values() if p['status'] != PositionStatus.CLOSED]

    def get_position(self, position_id: str) -> Optional[Dict]:
        """Get position by ID"""
        return self.positions.get(position_id)

    def update_position_pnl(self, position: Dict, current_premium: float):
        """
        Update unrealized P&L for position

        Args:
            position: Position dict
            current_premium: Current option premium
        """
        remaining_qty = position['remaining_quantity']
        unrealized_pnl = (current_premium - position['entry_premium']) * remaining_qty

        position['unrealized_pnl'] = unrealized_pnl
        position['current_premium'] = current_premium

    def _select_strike(
        self,
        spot: float,
        direction: str,
        min_otm: int,
        max_otm: int
    ) -> int:
        """
        Select optimal strike price

        Args:
            spot: Current spot price
            direction: 'CALL' or 'PUT'
            min_otm: Minimum OTM distance
            max_otm: Maximum OTM distance

        Returns:
            Selected strike price
        """
        strike_step = 50  # NIFTY strike step

        # Calculate target OTM distance (middle of range)
        target_otm = (min_otm + max_otm) // 2

        if direction == 'CALL':
            # For CALL, strike above spot
            target_strike = spot + target_otm
        else:  # PUT
            # For PUT, strike below spot
            target_strike = spot - target_otm

        # Round to nearest strike step
        strike = round(target_strike / strike_step) * strike_step

        self.logger.debug(
            f"Strike selection: Spot={spot:.0f}, Direction={direction}, "
            f"OTM={abs(strike - spot):.0f}, Strike={strike}"
        )

        return int(strike)

    def _find_expiry(
        self,
        target_dte_min: int,
        target_dte_max: int
    ) -> tuple:
        """
        Find optimal expiry within DTE range (THE EDGE: 10-14 days)

        Args:
            target_dte_min: Minimum DTE (10)
            target_dte_max: Maximum DTE (14)

        Returns:
            (expiry_date, expiry_str, actual_dte)
        """
        # NIFTY weekly expiry is on Thursday
        today = datetime.now().date()
        current_weekday = today.weekday()

        # Find next Thursday (weekday 3)
        days_until_thursday = (3 - current_weekday) % 7
        if days_until_thursday == 0:
            days_until_thursday = 7  # Skip to next Thursday

        next_expiry = today + timedelta(days=days_until_thursday)
        dte = days_until_thursday

        # If DTE is outside range, find next suitable expiry
        if dte < target_dte_min:
            # Need next week's expiry
            next_expiry = today + timedelta(days=days_until_thursday + 7)
            dte = days_until_thursday + 7
        elif dte > target_dte_max:
            # This shouldn't happen with weekly expiries, but handle it
            pass

        # Format expiry string (YYMMDD for Zerodha)
        expiry_str = next_expiry.strftime('%y%b%d').upper()

        self.logger.debug(
            f"Expiry selection: {next_expiry} ({expiry_str}) | DTE: {dte}"
        )

        return next_expiry, expiry_str, dte

    def _estimate_premium(
        self,
        spot: float,
        strike: int,
        dte: int,
        iv_percentile: float
    ) -> float:
        """
        Estimate option premium (simplified)

        In production, fetch actual premium from market

        Args:
            spot: Current spot price
            strike: Strike price
            dte: Days to expiry
            iv_percentile: IV percentile

        Returns:
            Estimated premium
        """
        # Simple estimation based on OTM distance and time
        otm_distance = abs(strike - spot)

        # Base premium from OTM distance
        base_premium = max(50, 500 - otm_distance * 1.5)

        # Time decay adjustment
        time_factor = dte / 14  # Normalize to 14 days
        base_premium *= time_factor

        # IV adjustment
        iv_factor = 1 + (iv_percentile - 50) / 100
        base_premium *= iv_factor

        return round(base_premium, 2)

    def _generate_position_id(self) -> str:
        """Generate unique position ID"""
        self.position_counter += 1
        timestamp = datetime.now().strftime('%Y%m%d%H%M%S')
        return f"POS_{timestamp}_{self.position_counter:03d}"

    # CRITICAL: NO roll_position() method
    # This method is deliberately NOT implemented per Gemini Fix #1
    # Rolling = averaging down on losing positions, which contradicts momentum logic
