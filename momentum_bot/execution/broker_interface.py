"""
Broker Interface for MCH Bot 3.0

Integrates with Zerodha Kite API for order execution
Supports both paper trading and live trading modes
"""

from typing import Dict, List, Optional
from datetime import datetime
import logging

from momentum_bot.core.constants import OrderSide, BrokerMode


class BrokerInterface:
    """
    Broker interface for order execution

    Supports:
    - Paper trading mode (simulation)
    - Kite API live trading
    - Order placement, modification, cancellation
    - Position tracking
    """

    def __init__(self, config):
        """
        Initialize broker interface

        Args:
            config: Config object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        self.broker_mode = config.execution_broker
        self.dry_run = config.execution_dry_run

        # Initialize Kite Connect if in live mode
        if self.broker_mode == "kite" and not self.dry_run:
            self._init_kite()
        else:
            self.kite = None
            self.logger.info("Paper trading mode enabled")

        # Paper trading state
        self.paper_orders = {}
        self.paper_order_counter = 0

        self.logger.info(
            f"BrokerInterface initialized: "
            f"Mode={self.broker_mode}, DryRun={self.dry_run}"
        )

    def _init_kite(self):
        """Initialize Kite Connect for live trading"""
        try:
            from kiteconnect import KiteConnect

            if not self.config.kite_api_key:
                raise ValueError("Kite API key not configured")

            self.kite = KiteConnect(api_key=self.config.kite_api_key)

            if self.config.kite_access_token:
                self.kite.set_access_token(self.config.kite_access_token)
                self.logger.info("Kite API initialized for live trading")
            else:
                raise ValueError("Kite access token not configured")

        except Exception as e:
            self.logger.error(f"Failed to initialize Kite API: {e}")
            self.logger.warning("Falling back to paper trading mode")
            self.kite = None

    async def place_order(self, position: Dict) -> Dict:
        """
        Place order for new position

        Args:
            position: Position dict containing:
                - instrument: Symbol
                - strike: Strike price
                - expiry_str: Expiry string (YYMMDD)
                - option_type: 'CALL' or 'PUT'
                - quantity: Order quantity
                - entry_premium: Limit price

        Returns:
            Order result dict
        """
        if self.kite is None or self.dry_run:
            return self._place_paper_order(position, OrderSide.BUY)
        else:
            return self._place_kite_order(position, OrderSide.BUY)

    async def close_position(
        self,
        position: Dict,
        quantity: int,
        exit_premium: float
    ) -> Dict:
        """
        Close position (sell)

        Args:
            position: Position dict
            quantity: Quantity to sell
            exit_premium: Limit price

        Returns:
            Order result dict
        """
        if self.kite is None or self.dry_run:
            return self._close_paper_position(position, quantity, exit_premium)
        else:
            return self._close_kite_position(position, quantity, exit_premium)

    def _place_paper_order(self, position: Dict, side: OrderSide) -> Dict:
        """
        Simulate order placement (paper trading)

        Args:
            position: Position dict
            side: Order side (BUY/SELL)

        Returns:
            Simulated order result
        """
        self.paper_order_counter += 1
        order_id = f"PAPER_{self.paper_order_counter:06d}"

        # Simulate slippage (Grok's 7.5%)
        slippage_rate = self.config.execution_slippage_rate
        entry_premium = position['entry_premium']

        if side == OrderSide.BUY:
            fill_price = entry_premium * (1 + slippage_rate)
        else:
            fill_price = entry_premium * (1 - slippage_rate)

        # Simulate brokerage
        brokerage = self.config.execution_brokerage_per_order

        order_result = {
            'success': True,
            'order_id': order_id,
            'position_id': position.get('position_id', 'unknown'),
            'symbol': self._construct_symbol(position),
            'side': side.value,
            'quantity': position['quantity'],
            'order_price': entry_premium,
            'fill_price': fill_price,
            'slippage': fill_price - entry_premium,
            'slippage_pct': slippage_rate * 100,
            'brokerage': brokerage,
            'timestamp': datetime.now(),
            'mode': 'PAPER'
        }

        self.paper_orders[order_id] = order_result

        self.logger.info(
            f"[PAPER] Order placed: {order_id} | "
            f"{side.value} {position['quantity']} x {self._construct_symbol(position)} "
            f"@ Rs.{fill_price:.2f} (slippage: {slippage_rate*100:.1f}%)"
        )

        return order_result

    def _place_kite_order(self, position: Dict, side: OrderSide) -> Dict:
        """
        Place order via Kite API (live trading)

        Args:
            position: Position dict
            side: Order side

        Returns:
            Order result dict
        """
        try:
            # Construct trading symbol
            symbol = self._construct_symbol(position)

            # Place order
            order_id = self.kite.place_order(
                variety=self.kite.VARIETY_REGULAR,
                exchange='NFO',
                tradingsymbol=symbol,
                transaction_type=self.kite.TRANSACTION_TYPE_BUY if side == OrderSide.BUY else self.kite.TRANSACTION_TYPE_SELL,
                quantity=position['quantity'],
                product=self.kite.PRODUCT_NRML,
                order_type=self.kite.ORDER_TYPE_LIMIT,
                price=round(position['entry_premium'], 2),
                validity=self.kite.VALIDITY_DAY
            )

            order_result = {
                'success': True,
                'order_id': order_id,
                'position_id': position.get('position_id', 'unknown'),
                'symbol': symbol,
                'side': side.value,
                'quantity': position['quantity'],
                'order_price': position['entry_premium'],
                'timestamp': datetime.now(),
                'mode': 'LIVE'
            }

            self.logger.info(
                f"[LIVE] Order placed: {order_id} | "
                f"{side.value} {position['quantity']} x {symbol} "
                f"@ Rs.{position['entry_premium']:.2f}"
            )

            return order_result

        except Exception as e:
            self.logger.error(f"Failed to place Kite order: {e}")
            return {
                'success': False,
                'error': str(e),
                'position_id': position.get('position_id', 'unknown')
            }

    def _close_paper_position(
        self,
        position: Dict,
        quantity: int,
        exit_premium: float
    ) -> Dict:
        """
        Close paper position

        Args:
            position: Position dict
            quantity: Quantity to close
            exit_premium: Exit price

        Returns:
            Close order result
        """
        self.paper_order_counter += 1
        order_id = f"PAPER_{self.paper_order_counter:06d}"

        # Simulate slippage
        slippage_rate = self.config.execution_slippage_rate
        fill_price = exit_premium * (1 - slippage_rate)

        # Calculate P&L
        entry_price = position['entry_premium']
        gross_pnl = (fill_price - entry_price) * quantity

        # Apply brokerage (entry + exit)
        brokerage = self.config.execution_brokerage_per_order * 2

        # Apply tax on profit
        tax = 0
        if gross_pnl > 0:
            tax = gross_pnl * self.config.execution_tax_rate

        net_pnl = gross_pnl - brokerage - tax

        order_result = {
            'success': True,
            'order_id': order_id,
            'position_id': position.get('position_id', 'unknown'),
            'symbol': self._construct_symbol(position),
            'side': OrderSide.SELL.value,
            'quantity': quantity,
            'order_price': exit_premium,
            'fill_price': fill_price,
            'slippage': exit_premium - fill_price,
            'gross_pnl': gross_pnl,
            'brokerage': brokerage,
            'tax': tax,
            'net_pnl': net_pnl,
            'timestamp': datetime.now(),
            'mode': 'PAPER'
        }

        self.logger.info(
            f"[PAPER] Position closed: {order_id} | "
            f"SELL {quantity} x {self._construct_symbol(position)} "
            f"@ Rs.{fill_price:.2f} | "
            f"P&L: Rs.{net_pnl:,.0f} (after costs)"
        )

        return order_result

    def _close_kite_position(
        self,
        position: Dict,
        quantity: int,
        exit_premium: float
    ) -> Dict:
        """
        Close position via Kite API

        Args:
            position: Position dict
            quantity: Quantity to close
            exit_premium: Exit price

        Returns:
            Order result dict
        """
        # Similar to _place_kite_order but with SELL side
        return self._place_kite_order(
            {**position, 'quantity': quantity, 'entry_premium': exit_premium},
            OrderSide.SELL
        )

    def _construct_symbol(self, position: Dict) -> str:
        """
        Construct Zerodha trading symbol

        Format: NIFTY25NOV23500CE

        Args:
            position: Position dict

        Returns:
            Trading symbol
        """
        instrument = position['instrument']
        expiry_str = position['expiry_str']
        strike = position['strike']
        option_type = position['option_type']

        symbol = f"{instrument}{expiry_str}{strike}{option_type}"

        return symbol

    def get_order_status(self, order_id: str) -> Optional[Dict]:
        """
        Get order status

        Args:
            order_id: Order ID

        Returns:
            Order status dict or None
        """
        if self.kite is None or self.dry_run:
            return self.paper_orders.get(order_id)
        else:
            try:
                orders = self.kite.orders()
                for order in orders:
                    if order['order_id'] == order_id:
                        return order
                return None
            except Exception as e:
                self.logger.error(f"Failed to get order status: {e}")
                return None

    def get_positions(self) -> List[Dict]:
        """
        Get current positions from broker

        Returns:
            List of position dicts
        """
        if self.kite is None or self.dry_run:
            return []  # Paper trading positions tracked separately
        else:
            try:
                return self.kite.positions()['net']
            except Exception as e:
                self.logger.error(f"Failed to get positions: {e}")
                return []
