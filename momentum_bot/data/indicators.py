"""
Technical Indicators for MCH Bot 3.0

Implements: ADX, RSI, MACD, EMA, VWAP, ATR, Bollinger Bands
"""

import numpy as np
import pandas as pd
from typing import Tuple


class TechnicalIndicators:
    """
    Collection of technical indicators for momentum detection
    and regime classification
    """

    @staticmethod
    def calculate_ema(prices: pd.Series, period: int) -> pd.Series:
        """
        Calculate Exponential Moving Average

        Args:
            prices: Series of prices
            period: EMA period

        Returns:
            Series of EMA values
        """
        return prices.ewm(span=period, adjust=False).mean()

    @staticmethod
    def calculate_sma(prices: pd.Series, period: int) -> pd.Series:
        """
        Calculate Simple Moving Average

        Args:
            prices: Series of prices
            period: SMA period

        Returns:
            Series of SMA values
        """
        return prices.rolling(window=period).mean()

    @staticmethod
    def calculate_rsi(prices: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculate Relative Strength Index (RSI)

        Args:
            prices: Series of closing prices
            period: RSI period (default 14)

        Returns:
            Series of RSI values (0-100)
        """
        delta = prices.diff()

        gain = (delta.where(delta > 0, 0)).rolling(window=period).mean()
        loss = (-delta.where(delta < 0, 0)).rolling(window=period).mean()

        rs = gain / loss
        rsi = 100 - (100 / (1 + rs))

        return rsi

    @staticmethod
    def calculate_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
        """
        Calculate Average True Range (ATR)

        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            period: ATR period (default 14)

        Returns:
            Series of ATR values
        """
        tr1 = high - low
        tr2 = abs(high - close.shift())
        tr3 = abs(low - close.shift())

        tr = pd.concat([tr1, tr2, tr3], axis=1).max(axis=1)
        atr = tr.rolling(window=period).mean()

        return atr

    @staticmethod
    def calculate_atr_percentile(atr: pd.Series, lookback: int = 252) -> float:
        """
        Calculate ATR percentile (0-100)

        Args:
            atr: Series of ATR values
            lookback: Lookback period for percentile calculation

        Returns:
            Current ATR percentile
        """
        if len(atr) < 2:
            return 50.0

        current_atr = atr.iloc[-1]
        historical_atr = atr.iloc[-lookback:] if len(atr) >= lookback else atr

        percentile = (historical_atr < current_atr).sum() / len(historical_atr) * 100

        return percentile

    @staticmethod
    def calculate_adx(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate ADX (Average Directional Index) with DI+ and DI-

        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            period: ADX period (default 14)

        Returns:
            Tuple of (adx, di_plus, di_minus) Series
        """
        # Calculate +DM and -DM
        high_diff = high.diff()
        low_diff = -low.diff()

        plus_dm = high_diff.where((high_diff > low_diff) & (high_diff > 0), 0)
        minus_dm = low_diff.where((low_diff > high_diff) & (low_diff > 0), 0)

        # Calculate ATR
        atr = TechnicalIndicators.calculate_atr(high, low, close, period)

        # Calculate +DI and -DI
        plus_di = 100 * (plus_dm.rolling(window=period).mean() / atr)
        minus_di = 100 * (minus_dm.rolling(window=period).mean() / atr)

        # Calculate DX and ADX
        dx = 100 * abs(plus_di - minus_di) / (plus_di + minus_di)
        adx = dx.rolling(window=period).mean()

        return adx, plus_di, minus_di

    @staticmethod
    def calculate_macd(prices: pd.Series, fast: int = 12, slow: int = 26, signal: int = 9) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate MACD (Moving Average Convergence Divergence)

        Args:
            prices: Series of closing prices
            fast: Fast EMA period (default 12)
            slow: Slow EMA period (default 26)
            signal: Signal line period (default 9)

        Returns:
            Tuple of (macd_line, signal_line, histogram) Series
        """
        ema_fast = TechnicalIndicators.calculate_ema(prices, fast)
        ema_slow = TechnicalIndicators.calculate_ema(prices, slow)

        macd_line = ema_fast - ema_slow
        signal_line = TechnicalIndicators.calculate_ema(macd_line, signal)
        histogram = macd_line - signal_line

        return macd_line, signal_line, histogram

    @staticmethod
    def calculate_vwap(high: pd.Series, low: pd.Series, close: pd.Series, volume: pd.Series) -> pd.Series:
        """
        Calculate VWAP (Volume Weighted Average Price)

        Args:
            high: Series of high prices
            low: Series of low prices
            close: Series of close prices
            volume: Series of volume

        Returns:
            Series of VWAP values
        """
        typical_price = (high + low + close) / 3
        vwap = (typical_price * volume).cumsum() / volume.cumsum()

        return vwap

    @staticmethod
    def calculate_bollinger_bands(prices: pd.Series, period: int = 20, std_dev: float = 2.0) -> Tuple[pd.Series, pd.Series, pd.Series]:
        """
        Calculate Bollinger Bands

        Args:
            prices: Series of closing prices
            period: SMA period (default 20)
            std_dev: Standard deviation multiplier (default 2.0)

        Returns:
            Tuple of (upper_band, middle_band, lower_band) Series
        """
        middle_band = TechnicalIndicators.calculate_sma(prices, period)
        std = prices.rolling(window=period).std()

        upper_band = middle_band + (std * std_dev)
        lower_band = middle_band - (std * std_dev)

        return upper_band, middle_band, lower_band

    @staticmethod
    def calculate_iv_percentile(iv_values: pd.Series, lookback: int = 252) -> float:
        """
        Calculate IV percentile (0-100)

        Args:
            iv_values: Series of IV values
            lookback: Lookback period (default 252 days = 1 year)

        Returns:
            Current IV percentile
        """
        if len(iv_values) < 2:
            return 50.0

        current_iv = iv_values.iloc[-1]
        historical_iv = iv_values.iloc[-lookback:] if len(iv_values) >= lookback else iv_values

        percentile = (historical_iv < current_iv).sum() / len(historical_iv) * 100

        return percentile

    @staticmethod
    def is_price_above_ema(current_price: float, ema: pd.Series) -> bool:
        """
        Check if current price is above EMA

        Args:
            current_price: Current market price
            ema: EMA series

        Returns:
            True if price above EMA
        """
        if len(ema) == 0:
            return False

        return current_price > ema.iloc[-1]

    @staticmethod
    def is_price_below_ema(current_price: float, ema: pd.Series) -> bool:
        """
        Check if current price is below EMA

        Args:
            current_price: Current market price
            ema: EMA series

        Returns:
            True if price below EMA
        """
        if len(ema) == 0:
            return False

        return current_price < ema.iloc[-1]

    @staticmethod
    def detect_ema_crossover(fast_ema: pd.Series, slow_ema: pd.Series) -> str:
        """
        Detect EMA crossover

        Args:
            fast_ema: Fast EMA series
            slow_ema: Slow EMA series

        Returns:
            'bullish', 'bearish', or 'none'
        """
        if len(fast_ema) < 2 or len(slow_ema) < 2:
            return 'none'

        # Current values
        fast_now = fast_ema.iloc[-1]
        slow_now = slow_ema.iloc[-1]

        # Previous values
        fast_prev = fast_ema.iloc[-2]
        slow_prev = slow_ema.iloc[-2]

        # Bullish crossover: fast crosses above slow
        if fast_prev <= slow_prev and fast_now > slow_now:
            return 'bullish'

        # Bearish crossover: fast crosses below slow
        if fast_prev >= slow_prev and fast_now < slow_now:
            return 'bearish'

        return 'none'

    @staticmethod
    def detect_macd_crossover(macd_line: pd.Series, signal_line: pd.Series) -> str:
        """
        Detect MACD signal crossover

        Args:
            macd_line: MACD line series
            signal_line: Signal line series

        Returns:
            'bullish', 'bearish', or 'none'
        """
        if len(macd_line) < 2 or len(signal_line) < 2:
            return 'none'

        # Current values
        macd_now = macd_line.iloc[-1]
        signal_now = signal_line.iloc[-1]

        # Previous values
        macd_prev = macd_line.iloc[-2]
        signal_prev = signal_line.iloc[-2]

        # Bullish crossover: MACD crosses above signal
        if macd_prev <= signal_prev and macd_now > signal_now:
            return 'bullish'

        # Bearish crossover: MACD crosses below signal
        if macd_prev >= signal_prev and macd_now < signal_now:
            return 'bearish'

        return 'none'
