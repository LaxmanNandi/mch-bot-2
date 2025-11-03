"""
Trade Logger for MCH Bot 3.0

Logs all trading activities to file for analysis
"""

import logging
import json
from datetime import datetime
from pathlib import Path
from typing import Dict


class TradeLogger:
    """
    Trade journal logger

    Logs:
    - Entry signals
    - Exit signals
    - Position P&L
    - Regime changes
    - Risk events
    """

    def __init__(self, config):
        """
        Initialize trade logger

        Args:
            config: Config object
        """
        self.config = config

        # Create logs directory
        self.logs_dir = Path('logs')
        self.logs_dir.mkdir(exist_ok=True)

        # Setup file handlers
        self.trade_log_file = self.logs_dir / f"trades_{datetime.now().strftime('%Y%m%d')}.jsonl"
        self.system_log_file = self.logs_dir / f"system_{datetime.now().strftime('%Y%m%d')}.log"

        # Configure logging
        self._setup_logging()

        self.logger = logging.getLogger(__name__)
        self.logger.info("TradeLogger initialized")

    def _setup_logging(self):
        """Setup logging configuration"""
        # Root logger
        logging.basicConfig(
            level=logging.INFO,
            format='%(asctime)s | %(name)s | %(levelname)s | %(message)s',
            handlers=[
                logging.FileHandler(self.system_log_file, encoding='utf-8'),
                logging.StreamHandler()
            ]
        )

    def log_entry(self, position: Dict, order_result: Dict):
        """
        Log position entry

        Args:
            position: Position dict
            order_result: Order result dict
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'event': 'ENTRY',
            'position_id': position.get('position_id'),
            'instrument': position.get('instrument'),
            'strike': position.get('strike'),
            'expiry': position.get('expiry_str'),
            'option_type': position.get('option_type'),
            'quantity': position.get('quantity'),
            'entry_premium': position.get('entry_premium'),
            'entry_spot': position.get('entry_spot'),
            'dte': position.get('dte'),
            'confidence': position.get('confidence'),
            'order_id': order_result.get('order_id'),
            'fill_price': order_result.get('fill_price'),
            'mode': order_result.get('mode')
        }

        self._write_trade_log(log_entry)

    def log_exit(self, position: Dict, exit_result: Dict, reason: str):
        """
        Log position exit

        Args:
            position: Position dict
            exit_result: Exit result dict
            reason: Exit reason
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'event': 'EXIT',
            'position_id': position.get('position_id'),
            'instrument': position.get('instrument'),
            'strike': position.get('strike'),
            'option_type': position.get('option_type'),
            'quantity': exit_result.get('exit_quantity'),
            'entry_premium': position.get('entry_premium'),
            'exit_premium': exit_result.get('exit_premium'),
            'pnl': exit_result.get('pnl'),
            'return_pct': exit_result.get('return_pct'),
            'reason': reason,
            'order_id': exit_result.get('order_id')
        }

        self._write_trade_log(log_entry)

    def log_regime_change(self, old_regime: str, new_regime: str, confidence: float):
        """
        Log regime change

        Args:
            old_regime: Old regime
            new_regime: New regime
            confidence: Regime confidence
        """
        log_entry = {
            'timestamp': datetime.now().isoformat(),
            'event': 'REGIME_CHANGE',
            'old_regime': old_regime,
            'new_regime': new_regime,
            'confidence': confidence
        }

        self._write_trade_log(log_entry)

    def _write_trade_log(self, log_entry: Dict):
        """
        Write log entry to JSONL file

        Args:
            log_entry: Log entry dict
        """
        with open(self.trade_log_file, 'a') as f:
            f.write(json.dumps(log_entry) + '\n')
