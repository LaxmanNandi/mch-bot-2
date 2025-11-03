"""
Market Data Feed for MCH Bot 3.0

Integrates with Zerodha Kite API for real-time market data
"""

import logging
import pandas as pd
from datetime import datetime, time, timedelta
from typing import Dict, Optional, List
from kiteconnect import KiteConnect
import pytz

from momentum_bot.data.indicators import TechnicalIndicators


class MarketDataFeed:
    """
    Market data feed using Zerodha Kite API

    Provides:
    - Real-time spot prices
    - Historical data for indicators
    - Option chain data
    - VIX data
    - Calculated technical indicators
    """

    def __init__(self, config):
        """
        Initialize market data feed

        Args:
            config: Config object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

        # Initialize Kite Connect
        if config.kite_api_key:
            self.kite = KiteConnect(api_key=config.kite_api_key)
            if config.kite_access_token:
                self.kite.set_access_token(config.kite_access_token)
                self.logger.info("Kite API initialized with access token")
            else:
                self.logger.warning("Kite API initialized but no access token set")
        else:
            self.kite = None
            self.logger.warning("Kite API not configured - using demo mode")

        # Cache for historical data
        self.historical_cache = {}
        self.cache_expiry = {}

        # Instrument tokens (will be fetched dynamically)
        self.instrument_tokens = {}

        # Timezone
        self.tz = pytz.timezone(config.market_timezone)

    def is_market_open(self) -> bool:
        """
        Check if market is currently open

        Returns:
            True if market is open
        """
        now = datetime.now(self.tz)

        # Check if weekend
        if now.weekday() >= 5:  # Saturday=5, Sunday=6
            return False

        # Parse market hours
        open_time = time.fromisoformat(self.config.market_open)
        close_time = time.fromisoformat(self.config.market_close)

        # Check if within market hours
        current_time = now.time()

        return open_time <= current_time <= close_time

    async def get_latest(self) -> Dict:
        """
        Get latest market data with all indicators

        Returns:
            Dict containing:
                - spot: Current spot price
                - vix: Current VIX value
                - adx: ADX value
                - di_plus: DI+ value
                - di_minus: DI- value
                - rsi: RSI value
                - macd: MACD line value
                - macd_signal: MACD signal line
                - macd_histogram: MACD histogram
                - ema_20: 20-period EMA
                - atr: ATR value
                - atr_percentile: ATR percentile
                - iv_percentile: IV percentile
                - timestamp: Data timestamp
        """
        # Get spot price
        spot = await self.get_spot_price()

        # Get VIX
        vix = await self.get_vix()

        # Get historical data for indicators (60 days)
        hist_data = await self.get_historical_data(
            symbol=self.config.instrument_symbol,
            days=60
        )

        # Calculate indicators
        indicators = self._calculate_all_indicators(hist_data, spot)

        # Combine all data
        market_data = {
            'spot': spot,
            'vix': vix,
            'timestamp': datetime.now(self.tz),
            **indicators
        }

        return market_data

    async def get_spot_price(self) -> float:
        """
        Get current spot price for underlying

        Returns:
            Current spot price
        """
        if self.kite is None:
            # Demo mode
            return self.config.get('demo.spot', 23500)

        try:
            symbol = self.config.instrument_underlying_symbol
            quote = self.kite.quote(symbol)

            if symbol in quote:
                return quote[symbol]['last_price']
            else:
                self.logger.error(f"Quote not found for {symbol}")
                return 0.0

        except Exception as e:
            self.logger.error(f"Error fetching spot price: {e}")
            return 0.0

    async def get_vix(self) -> float:
        """
        Get current VIX value

        Returns:
            Current VIX value
        """
        if self.kite is None:
            # Demo mode
            return self.config.get('demo.iv', 0.18) * 100

        try:
            vix_symbol = "NSE:INDIA VIX"
            quote = self.kite.quote(vix_symbol)

            if vix_symbol in quote:
                return quote[vix_symbol]['last_price']
            else:
                self.logger.error("VIX quote not found")
                return 15.0  # Default value

        except Exception as e:
            self.logger.error(f"Error fetching VIX: {e}")
            return 15.0

    async def get_historical_data(
        self,
        symbol: str,
        days: int = 60,
        interval: str = "day"
    ) -> pd.DataFrame:
        """
        Get historical OHLCV data

        Args:
            symbol: Instrument symbol
            days: Number of days of history
            interval: Data interval (day, minute, etc.)

        Returns:
            DataFrame with OHLCV data
        """
        # Check cache
        cache_key = f"{symbol}_{days}_{interval}"
        if cache_key in self.historical_cache:
            expiry = self.cache_expiry.get(cache_key)
            if expiry and datetime.now() < expiry:
                return self.historical_cache[cache_key]

        if self.kite is None:
            # Demo mode - generate synthetic data
            return self._generate_demo_data(days)

        try:
            # Get instrument token
            instrument_token = await self._get_instrument_token(symbol)

            # Calculate date range
            to_date = datetime.now()
            from_date = to_date - timedelta(days=days)

            # Fetch historical data
            historical = self.kite.historical_data(
                instrument_token=instrument_token,
                from_date=from_date,
                to_date=to_date,
                interval=interval
            )

            # Convert to DataFrame
            df = pd.DataFrame(historical)
            df['date'] = pd.to_datetime(df['date'])
            df.set_index('date', inplace=True)

            # Cache for 1 hour
            self.historical_cache[cache_key] = df
            self.cache_expiry[cache_key] = datetime.now() + timedelta(hours=1)

            return df

        except Exception as e:
            self.logger.error(f"Error fetching historical data: {e}")
            return pd.DataFrame()

    def _calculate_all_indicators(self, hist_data: pd.DataFrame, current_spot: float) -> Dict:
        """
        Calculate all technical indicators

        Args:
            hist_data: Historical OHLCV data
            current_spot: Current spot price

        Returns:
            Dict of indicator values
        """
        if hist_data.empty or len(hist_data) < 30:
            self.logger.warning("Insufficient historical data for indicators")
            return self._default_indicators()

        try:
            # Extract OHLCV
            close = hist_data['close']
            high = hist_data['high']
            low = hist_data['low']
            volume = hist_data.get('volume', pd.Series([0] * len(hist_data)))

            # Calculate indicators
            adx, di_plus, di_minus = TechnicalIndicators.calculate_adx(high, low, close)
            rsi = TechnicalIndicators.calculate_rsi(close)
            macd_line, signal_line, histogram = TechnicalIndicators.calculate_macd(close)
            ema_20 = TechnicalIndicators.calculate_ema(close, 20)
            atr = TechnicalIndicators.calculate_atr(high, low, close)
            atr_percentile = TechnicalIndicators.calculate_atr_percentile(atr)

            # IV percentile (placeholder - would need option data)
            iv_percentile = 50.0  # Default

            return {
                'adx': adx.iloc[-1] if not adx.empty else 20.0,
                'di_plus': di_plus.iloc[-1] if not di_plus.empty else 20.0,
                'di_minus': di_minus.iloc[-1] if not di_minus.empty else 20.0,
                'rsi': rsi.iloc[-1] if not rsi.empty else 50.0,
                'macd': macd_line.iloc[-1] if not macd_line.empty else 0.0,
                'macd_signal': signal_line.iloc[-1] if not signal_line.empty else 0.0,
                'macd_histogram': histogram.iloc[-1] if not histogram.empty else 0.0,
                'ema_20': ema_20.iloc[-1] if not ema_20.empty else current_spot,
                'atr': atr.iloc[-1] if not atr.empty else current_spot * 0.01,
                'atr_percentile': atr_percentile,
                'iv_percentile': iv_percentile
            }

        except Exception as e:
            self.logger.error(f"Error calculating indicators: {e}")
            return self._default_indicators()

    def _default_indicators(self) -> Dict:
        """Return default indicator values when calculation fails"""
        return {
            'adx': 20.0,
            'di_plus': 20.0,
            'di_minus': 20.0,
            'rsi': 50.0,
            'macd': 0.0,
            'macd_signal': 0.0,
            'macd_histogram': 0.0,
            'ema_20': 23500.0,
            'atr': 235.0,
            'atr_percentile': 50.0,
            'iv_percentile': 50.0
        }

    def _generate_demo_data(self, days: int) -> pd.DataFrame:
        """Generate synthetic data for demo mode"""
        import numpy as np

        dates = pd.date_range(end=datetime.now(), periods=days, freq='D')

        # Generate random walk for prices
        returns = np.random.normal(0.001, 0.02, days)
        prices = 23500 * (1 + returns).cumprod()

        df = pd.DataFrame({
            'open': prices * np.random.uniform(0.995, 1.005, days),
            'high': prices * np.random.uniform(1.005, 1.015, days),
            'low': prices * np.random.uniform(0.985, 0.995, days),
            'close': prices,
            'volume': np.random.randint(100000, 1000000, days)
        }, index=dates)

        return df

    async def _get_instrument_token(self, symbol: str) -> int:
        """
        Get instrument token for symbol

        Args:
            symbol: Instrument symbol

        Returns:
            Instrument token
        """
        # Check cache
        if symbol in self.instrument_tokens:
            return self.instrument_tokens[symbol]

        if self.kite is None:
            return 0

        try:
            # Fetch instruments
            instruments = self.kite.instruments("NSE")

            # Find matching instrument
            search_symbol = symbol.split(':')[-1].replace(' 50', '').strip()

            for inst in instruments:
                # Check both tradingsymbol and name fields
                if (inst.get('tradingsymbol') == search_symbol or
                    inst.get('name') == symbol or
                    inst.get('name') == search_symbol or
                    (search_symbol == 'NIFTY' and inst.get('name') == 'NIFTY 50')):
                    token = inst['instrument_token']
                    self.instrument_tokens[symbol] = token
                    self.logger.info(f"Found instrument token for {symbol}: {token}")
                    return token

            self.logger.error(f"Instrument token not found for {symbol}")
            return 0

        except Exception as e:
            self.logger.error(f"Error fetching instrument token: {e}")
            return 0

    async def get_option_premium(
        self,
        strike: int,
        expiry: str,
        option_type: str
    ) -> float:
        """
        Get current option premium

        Args:
            strike: Strike price
            expiry: Expiry date (YYMMDD format)
            option_type: 'CE' or 'PE'

        Returns:
            Current option premium
        """
        if self.kite is None:
            # Demo mode - simple BSM approximation
            spot = await self.get_spot_price()
            otm_distance = abs(strike - spot)
            return max(50, 500 - otm_distance * 1.5)

        try:
            # Construct tradingsymbol
            symbol = f"NFO:NIFTY{expiry}{strike}{option_type}"

            quote = self.kite.quote(symbol)

            if symbol in quote:
                return quote[symbol]['last_price']
            else:
                self.logger.error(f"Option quote not found for {symbol}")
                return 0.0

        except Exception as e:
            self.logger.error(f"Error fetching option premium: {e}")
            return 0.0
