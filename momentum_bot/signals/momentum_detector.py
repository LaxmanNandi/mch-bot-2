"""
Momentum Detector for MCH Bot 3.0

Implements Gemini's simplified 5-factor momentum detection:
1. Regime (handled by master controller) ✓
2. Timing (DTE 10-14) ✓
3. Trend (ADX > 25, Spot > EMA-20) ✓
4. Entry (RSI < 70) ✓
5. Valuation (IV < 80 percentile) ✓
"""

from typing import Dict, Tuple
import logging


class MomentumDetector:
    """
    Detects bullish/bearish momentum using Gemini's 5-factor model

    The regime factor (#1) is already filtered by Master Portfolio Controller,
    so this detector focuses on factors 2-5.
    """

    def __init__(self, config):
        """
        Initialize momentum detector

        Args:
            config: Config object
        """
        self.adx_threshold = config.entry_adx_threshold
        self.ema_period = config.entry_ema_period
        self.rsi_max = config.entry_rsi_max
        self.iv_percentile_max = config.entry_iv_percentile_max

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"MomentumDetector initialized: "
            f"ADX>{self.adx_threshold}, RSI<{self.rsi_max}, IV<{self.iv_percentile_max}%"
        )

    def detect_bullish_momentum(self, data: Dict) -> Tuple[bool, Dict]:
        """
        Detect bullish momentum (for CALL options)

        Args:
            data: Market data dict containing:
                - spot: Current spot price
                - adx: ADX value
                - ema_20: 20-period EMA
                - rsi: RSI value
                - iv_percentile: IV percentile
                - di_plus: DI+ value
                - di_minus: DI- value

        Returns:
            (is_bullish: bool, factors: dict)
        """
        factors = {}

        # Factor 3: Trend Filter
        factors['adx_strong'] = data['adx'] > self.adx_threshold
        factors['price_above_ema'] = data['spot'] > data[f'ema_{self.ema_period}']
        factors['bullish_direction'] = data.get('di_plus', 0) > data.get('di_minus', 0)

        # Combined trend condition
        factors['trend'] = (
            factors['adx_strong'] and
            factors['price_above_ema'] and
            factors['bullish_direction']
        )

        # Factor 4: Entry Filter (not overbought)
        factors['rsi_ok'] = data['rsi'] < self.rsi_max
        factors['rsi'] = factors['rsi_ok']

        # Factor 5: Valuation Filter (IV not too high)
        factors['iv_ok'] = data['iv_percentile'] < self.iv_percentile_max
        factors['iv_percentile'] = factors['iv_ok']

        # All factors must be True for bullish signal
        is_bullish = all([
            factors['trend'],
            factors['rsi'],
            factors['iv_percentile']
        ])

        # Log signal details
        if is_bullish:
            self.logger.info(
                f"✓ BULLISH MOMENTUM DETECTED: "
                f"ADX={data['adx']:.1f}, "
                f"Spot={data['spot']:.0f} > EMA={data[f'ema_{self.ema_period}']:.0f}, "
                f"RSI={data['rsi']:.1f}, "
                f"IV%={data['iv_percentile']:.0f}"
            )
        else:
            failed_factors = [k for k, v in factors.items() if not v and k in ['trend', 'rsi', 'iv_percentile']]
            self.logger.debug(
                f"✗ Bullish momentum FAILED: {', '.join(failed_factors)}"
            )

        return is_bullish, factors

    def detect_bearish_momentum(self, data: Dict) -> Tuple[bool, Dict]:
        """
        Detect bearish momentum (for PUT options)

        Args:
            data: Market data dict (same as detect_bullish_momentum)

        Returns:
            (is_bearish: bool, factors: dict)
        """
        factors = {}

        # Factor 3: Trend Filter (inverted for bearish)
        factors['adx_strong'] = data['adx'] > self.adx_threshold
        factors['price_below_ema'] = data['spot'] < data[f'ema_{self.ema_period}']
        factors['bearish_direction'] = data.get('di_minus', 0) > data.get('di_plus', 0)

        # Combined trend condition
        factors['trend'] = (
            factors['adx_strong'] and
            factors['price_below_ema'] and
            factors['bearish_direction']
        )

        # Factor 4: Entry Filter (not oversold for puts - use inverse RSI)
        # For puts, we want RSI not too low (not oversold)
        factors['rsi_ok'] = data['rsi'] > (100 - self.rsi_max)  # Mirror logic
        factors['rsi'] = factors['rsi_ok']

        # Factor 5: Valuation Filter (same as bullish)
        factors['iv_ok'] = data['iv_percentile'] < self.iv_percentile_max
        factors['iv_percentile'] = factors['iv_ok']

        # All factors must be True for bearish signal
        is_bearish = all([
            factors['trend'],
            factors['rsi'],
            factors['iv_percentile']
        ])

        # Log signal details
        if is_bearish:
            self.logger.info(
                f"✓ BEARISH MOMENTUM DETECTED: "
                f"ADX={data['adx']:.1f}, "
                f"Spot={data['spot']:.0f} < EMA={data[f'ema_{self.ema_period}']:.0f}, "
                f"RSI={data['rsi']:.1f}, "
                f"IV%={data['iv_percentile']:.0f}"
            )
        else:
            failed_factors = [k for k, v in factors.items() if not v and k in ['trend', 'rsi', 'iv_percentile']]
            self.logger.debug(
                f"✗ Bearish momentum FAILED: {', '.join(failed_factors)}"
            )

        return is_bearish, factors

    def get_factor_scores(self, factors: Dict) -> Dict[str, float]:
        """
        Convert boolean factors to 0-100 scores

        Args:
            factors: Factor dict from detect_bullish/bearish_momentum

        Returns:
            Dict of factor scores (0-100)
        """
        scores = {}

        # Convert boolean to score
        scores['trend_score'] = 100.0 if factors.get('trend', False) else 0.0
        scores['rsi_score'] = 100.0 if factors.get('rsi', False) else 0.0
        scores['iv_score'] = 100.0 if factors.get('iv_percentile', False) else 0.0

        return scores

    def get_momentum_strength(self, data: Dict, is_bullish: bool) -> float:
        """
        Calculate momentum strength (0-100)

        Args:
            data: Market data dict
            is_bullish: Whether checking bullish or bearish momentum

        Returns:
            Momentum strength score (0-100)
        """
        strength = 0.0

        # ADX strength (0-30 range normalized to 0-100)
        adx_strength = min((data['adx'] / 30) * 100, 100)
        strength += adx_strength * 0.4  # 40% weight

        # Directional clarity (DI difference)
        di_diff = abs(data.get('di_plus', 0) - data.get('di_minus', 0))
        di_strength = min((di_diff / 30) * 100, 100)
        strength += di_strength * 0.3  # 30% weight

        # EMA distance (price deviation from EMA)
        ema_distance = abs(data['spot'] - data[f'ema_{self.ema_period}']) / data['spot'] * 100
        ema_strength = min(ema_distance * 50, 100)  # 2% = 100 strength
        strength += ema_strength * 0.3  # 30% weight

        return min(strength, 100.0)
