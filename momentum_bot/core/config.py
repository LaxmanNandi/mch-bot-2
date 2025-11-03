"""
Configuration loader for MCH Bot 3.0
Loads from YAML and overrides with environment variables
"""

import os
from pathlib import Path
from typing import Any, Dict, Optional
import yaml
from datetime import time

# Load .env file if it exists
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass  # python-dotenv not installed, skip


class Config:
    """
    Configuration manager for Bot 3.0

    Loads configuration from config_bot3.yaml
    Overrides sensitive data from environment variables
    """

    def __init__(self, config_path: Optional[str] = None):
        """
        Initialize configuration

        Args:
            config_path: Path to YAML config file (default: config_bot3.yaml)
        """
        if config_path is None:
            config_path = Path(__file__).parent.parent.parent / "config_bot3.yaml"

        self._config = self._load_yaml(config_path)
        self._apply_env_overrides()
        self._validate()

    def _load_yaml(self, path: Path) -> Dict[str, Any]:
        """Load YAML configuration file"""
        if not Path(path).exists():
            raise FileNotFoundError(f"Config file not found: {path}")

        with open(path, 'r') as f:
            return yaml.safe_load(f)

    def _apply_env_overrides(self):
        """Override sensitive configuration with environment variables"""
        # Kite API credentials
        if os.getenv('KITE_API_KEY'):
            self._config['kite']['api_key'] = os.getenv('KITE_API_KEY')
        if os.getenv('KITE_API_SECRET'):
            self._config['kite']['api_secret'] = os.getenv('KITE_API_SECRET')
        if os.getenv('KITE_ACCESS_TOKEN'):
            self._config['kite']['access_token'] = os.getenv('KITE_ACCESS_TOKEN')

        # Telegram credentials
        if os.getenv('TELEGRAM_BOT_TOKEN'):
            self._config['telegram']['bot_token'] = os.getenv('TELEGRAM_BOT_TOKEN')
        if os.getenv('TELEGRAM_CHAT_ID'):
            self._config['telegram']['chat_id'] = os.getenv('TELEGRAM_CHAT_ID')

        # Override mode for testing
        if os.getenv('TELEGRAM_MODE'):
            self._config['telegram']['override_mode'] = os.getenv('TELEGRAM_MODE')

    def _validate(self):
        """Validate critical configuration parameters"""
        # Ensure rolling is disabled (Gemini Fix #1)
        if self._config.get('rolling', {}).get('enabled', False):
            raise ValueError(
                "CRITICAL ERROR: Rolling is enabled! "
                "This violates Gemini Fix #1. Set rolling.enabled = false"
            )

        # Validate capital and risk limits
        if self.capital <= 0:
            raise ValueError(f"Invalid capital: {self.capital}")

        if self.max_positions < 1:
            raise ValueError(f"Invalid max_positions: {self.max_positions}")

        # Validate DTE range (THE EDGE)
        if not (10 <= self.entry_dte_min <= self.entry_dte_max <= 14):
            raise ValueError(
                f"DTE must be in range 10-14 (THE EDGE). "
                f"Got: {self.entry_dte_min}-{self.entry_dte_max}"
            )

    # Capital & Risk properties
    @property
    def capital(self) -> int:
        return self._config['capital']

    @property
    def max_capital_per_trade_base(self) -> float:
        return self._config['max_capital_per_trade_base']

    @property
    def max_capital_per_trade_max(self) -> float:
        return self._config['max_capital_per_trade_max']

    @property
    def max_loss_per_trade(self) -> int:
        return self._config['max_loss_per_trade']

    @property
    def max_daily_loss(self) -> int:
        return self._config['max_daily_loss']

    @property
    def max_weekly_loss(self) -> int:
        return self._config['max_weekly_loss']

    @property
    def max_positions(self) -> int:
        return self._config['max_positions']

    # Entry parameters
    @property
    def entry_dte_min(self) -> int:
        return self._config['entry']['dte_min']

    @property
    def entry_dte_max(self) -> int:
        return self._config['entry']['dte_max']

    @property
    def entry_strike_distance_min(self) -> int:
        return self._config['entry']['strike_distance_min']

    @property
    def entry_strike_distance_max(self) -> int:
        return self._config['entry']['strike_distance_max']

    @property
    def entry_adx_threshold(self) -> float:
        return self._config['entry']['adx_threshold']

    @property
    def entry_ema_period(self) -> int:
        return self._config['entry']['ema_period']

    @property
    def entry_rsi_max(self) -> float:
        return self._config['entry']['rsi_max']

    @property
    def entry_iv_percentile_max(self) -> float:
        return self._config['entry']['iv_percentile_max']

    @property
    def entry_window_start(self) -> str:
        return self._config['entry']['entry_window_start']

    @property
    def entry_window_end(self) -> str:
        return self._config['entry']['entry_window_end']

    # Exit parameters
    @property
    def exit_profit_target_pct(self) -> float:
        return self._config['exit']['profit_target_pct']

    @property
    def exit_partial_exit_pct(self) -> float:
        return self._config['exit']['partial_exit_pct']

    @property
    def exit_stop_loss_pct(self) -> float:
        return self._config['exit']['stop_loss_pct']

    @property
    def exit_time_exit_dte(self) -> int:
        return self._config['exit']['time_exit_dte']

    @property
    def exit_wednesday_exit(self) -> bool:
        return self._config['exit']['wednesday_exit']

    @property
    def exit_iv_crush_threshold(self) -> float:
        return self._config['exit']['iv_crush_threshold']

    @property
    def exit_trailing_method(self) -> str:
        return self._config['exit']['trailing_method']

    # Risk adjustments
    @property
    def risk_weekend_max_capital(self) -> float:
        return self._config['risk']['weekend_max_capital']

    @property
    def risk_event_max_capital(self) -> float:
        return self._config['risk']['event_max_capital']

    # Regime classification
    @property
    def regime_adx_trending(self) -> float:
        return self._config['regime']['adx_trending']

    @property
    def regime_adx_ranging(self) -> float:
        return self._config['regime']['adx_ranging']

    @property
    def regime_vix_volatile(self) -> float:
        return self._config['regime']['vix_volatile']

    @property
    def regime_atr_percentile_high(self) -> float:
        return self._config['regime']['atr_percentile_high']

    # Execution
    @property
    def execution_broker(self) -> str:
        return self._config['execution']['broker']

    @property
    def execution_dry_run(self) -> bool:
        return self._config['execution']['dry_run']

    @property
    def execution_slippage_rate(self) -> float:
        return self._config['execution']['slippage_rate']

    @property
    def execution_brokerage_per_order(self) -> float:
        return self._config['execution']['brokerage_per_order']

    @property
    def execution_tax_rate(self) -> float:
        return self._config['execution']['tax_rate']

    # Telegram
    @property
    def telegram_bot_token(self) -> str:
        return self._config['telegram']['bot_token']

    @property
    def telegram_chat_id(self) -> str:
        return self._config['telegram']['chat_id']

    @property
    def telegram_override_mode(self) -> str:
        return self._config['telegram']['override_mode']

    # Kite API
    @property
    def kite_api_key(self) -> str:
        return self._config['kite']['api_key']

    @property
    def kite_api_secret(self) -> str:
        return self._config['kite']['api_secret']

    @property
    def kite_access_token(self) -> str:
        return self._config['kite']['access_token']

    # Instrument
    @property
    def instrument_symbol(self) -> str:
        return self._config['instrument']['symbol']

    @property
    def instrument_lot_size(self) -> int:
        return self._config['instrument']['lot_size']

    @property
    def instrument_underlying_symbol(self) -> str:
        return self._config['instrument']['underlying_symbol_zerodha']

    # Market hours
    @property
    def market_open(self) -> str:
        return self._config['market']['open']

    @property
    def market_close(self) -> str:
        return self._config['market']['close']

    @property
    def market_timezone(self) -> str:
        return self._config['market']['timezone']

    # Utility methods
    def get(self, key: str, default: Any = None) -> Any:
        """Get configuration value by key"""
        keys = key.split('.')
        value = self._config
        for k in keys:
            if isinstance(value, dict):
                value = value.get(k)
                if value is None:
                    return default
            else:
                return default
        return value

    def is_paper_trading(self) -> bool:
        """Check if in paper trading mode"""
        return self.execution_broker == "paper" or self.execution_dry_run

    def is_rolling_enabled(self) -> bool:
        """
        Check if rolling is enabled
        MUST ALWAYS RETURN FALSE (Gemini Fix #1)
        """
        return False  # Hardcoded to prevent accidental enabling
