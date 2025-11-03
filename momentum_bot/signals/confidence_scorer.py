"""
Confidence Scorer for MCH Bot 3.0

Calculates 0-100 confidence score for trade signals
Used for asymmetric position sizing
"""

from typing import Dict, Tuple
import logging


class ConfidenceScorer:
    """
    Calculate confidence score (0-100) for trade signals

    Higher confidence = larger position size (up to 45% capital)
    Lower confidence = smaller position size (35% capital minimum)

    Factors considered:
    - Regime confidence
    - Momentum strength
    - Factor alignment
    - VIX level
    - Market context
    """

    def __init__(self, config):
        """
        Initialize confidence scorer

        Args:
            config: Config object
        """
        self.config = config
        self.logger = logging.getLogger(__name__)

    def calculate(
        self,
        market_data: Dict,
        momentum_factors: Dict,
        regime_confidence: float = 0.8
    ) -> float:
        """
        Calculate overall confidence score

        Args:
            market_data: Market data dict
            momentum_factors: Factors from momentum detector
            regime_confidence: Confidence from regime classifier (0-1)

        Returns:
            Confidence score (0-100)
        """
        scores = []
        weights = []

        # 1. Regime Confidence (25% weight)
        regime_score = regime_confidence * 100
        scores.append(regime_score)
        weights.append(0.25)

        # 2. Momentum Factor Alignment (30% weight)
        factor_score = self._calculate_factor_score(momentum_factors)
        scores.append(factor_score)
        weights.append(0.30)

        # 3. ADX Strength (20% weight)
        adx_score = self._calculate_adx_score(market_data['adx'])
        scores.append(adx_score)
        weights.append(0.20)

        # 4. VIX Level (15% weight) - Lower VIX = higher confidence
        vix_score = self._calculate_vix_score(market_data['vix'])
        scores.append(vix_score)
        weights.append(0.15)

        # 5. RSI Position (10% weight) - Not extreme = higher confidence
        rsi_score = self._calculate_rsi_score(market_data['rsi'])
        scores.append(rsi_score)
        weights.append(0.10)

        # Weighted average
        confidence = sum(s * w for s, w in zip(scores, weights))

        # Floor at 0 and cap at 100
        confidence = max(0.0, min(100.0, confidence))

        self.logger.debug(
            f"Confidence: {confidence:.1f} "
            f"(Regime={regime_score:.0f}, Factors={factor_score:.0f}, "
            f"ADX={adx_score:.0f}, VIX={vix_score:.0f}, RSI={rsi_score:.0f})"
        )

        return confidence

    def _calculate_factor_score(self, factors: Dict) -> float:
        """
        Calculate score based on how many factors are satisfied

        Args:
            factors: Momentum factors dict

        Returns:
            Score (0-100)
        """
        required_factors = ['trend', 'rsi', 'iv_percentile']

        satisfied = sum(1 for f in required_factors if factors.get(f, False))
        total = len(required_factors)

        return (satisfied / total) * 100

    def _calculate_adx_score(self, adx: float) -> float:
        """
        Calculate score based on ADX strength

        Args:
            adx: ADX value

        Returns:
            Score (0-100)
        """
        # ADX interpretation:
        # 0-20: Weak/no trend (low score)
        # 20-25: Emerging trend (medium score)
        # 25-40: Strong trend (high score)
        # 40+: Very strong trend (very high score)

        if adx < 20:
            return 30.0  # Weak trend
        elif adx < 25:
            # Linear interpolation 20-25 -> 30-60
            return 30 + (adx - 20) * 6
        elif adx < 40:
            # Linear interpolation 25-40 -> 60-95
            return 60 + (adx - 25) * 2.33
        else:
            return min(95 + (adx - 40) * 0.5, 100)  # Cap at 100

    def _calculate_vix_score(self, vix: float) -> float:
        """
        Calculate score based on VIX level

        Lower VIX = Higher confidence (less market fear)

        Args:
            vix: VIX value

        Returns:
            Score (0-100)
        """
        # VIX interpretation:
        # <12: Very low volatility (very high confidence)
        # 12-16: Low-normal volatility (high confidence)
        # 16-20: Normal-elevated volatility (medium confidence)
        # 20-30: High volatility (low confidence)
        # >30: Extreme volatility (very low confidence)

        if vix < 12:
            return 95.0
        elif vix < 16:
            # Linear interpolation 12-16 -> 95-75
            return 95 - (vix - 12) * 5
        elif vix < 20:
            # Linear interpolation 16-20 -> 75-50
            return 75 - (vix - 16) * 6.25
        elif vix < 30:
            # Linear interpolation 20-30 -> 50-20
            return 50 - (vix - 20) * 3
        else:
            return max(20 - (vix - 30) * 2, 0)  # Floor at 0

    def _calculate_rsi_score(self, rsi: float) -> float:
        """
        Calculate score based on RSI position

        Ideal RSI: 40-60 (neutral zone)
        Extreme RSI: <30 or >70 (lower confidence)

        Args:
            rsi: RSI value (0-100)

        Returns:
            Score (0-100)
        """
        # RSI interpretation:
        # 40-60: Ideal neutral zone (high confidence)
        # 30-40, 60-70: Acceptable (medium confidence)
        # <30, >70: Extreme (low confidence)

        if 40 <= rsi <= 60:
            # Neutral zone - highest confidence
            return 100.0
        elif 30 <= rsi < 40:
            # Below neutral - still ok
            return 60 + (rsi - 30) * 4
        elif 60 < rsi <= 70:
            # Above neutral - still ok
            return 100 - (rsi - 60) * 4
        elif rsi < 30:
            # Oversold - lower confidence
            return max(30 + rsi, 0)
        else:  # rsi > 70
            # Overbought - lower confidence
            return max(100 - (rsi - 70), 0)

    def get_position_size_multiplier(self, confidence: float) -> float:
        """
        Get position size multiplier based on confidence

        Args:
            confidence: Confidence score (0-100)

        Returns:
            Multiplier for base position size (0.8 - 1.2)
        """
        # Confidence to multiplier mapping:
        # 85-100: 1.2x (45% capital vs 35% base)
        # 70-85: 1.0x (35% capital)
        # 50-70: 0.9x (31.5% capital)
        # <50: 0.8x (28% capital)

        if confidence >= 85:
            return 1.2  # Max position
        elif confidence >= 70:
            return 1.0  # Base position
        elif confidence >= 50:
            return 0.9  # Reduced position
        else:
            return 0.8  # Minimum position

    def should_take_trade(self, confidence: float) -> Tuple[bool, str]:
        """
        Determine if trade should be taken based on confidence

        Args:
            confidence: Confidence score (0-100)

        Returns:
            (should_trade: bool, reason: str)
        """
        min_confidence = self.config.get('entry.min_confidence', 70)

        if confidence >= min_confidence:
            if confidence >= 85:
                return True, f"High confidence ({confidence:.0f}%) - full size position"
            elif confidence >= 70:
                return True, f"Good confidence ({confidence:.0f}%) - standard size"
            else:
                return True, f"Adequate confidence ({confidence:.0f}%) - reduced size"
        else:
            return False, f"Insufficient confidence ({confidence:.0f}% < {min_confidence}%)"
