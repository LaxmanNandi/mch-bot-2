"""
Market Regime Classifier for MCH Bot 3.0

CRITICAL MODULE - Part of Gemini Fix #2
Classifies market regime: TRENDING / RANGING / VOLATILE / CHOPPY
This is the MASTER SWITCH for entire portfolio strategy selection
"""

from typing import Dict, Tuple
import logging
from momentum_bot.core.constants import MarketRegime


class RegimeClassifier:
    """
    Determines current market regime using multiple indicators

    Regime Definitions:
    - TRENDING: ADX > 25, clear direction, low VIX
    - RANGING: ADX < 20, price oscillating, normal VIX
    - VOLATILE: High VIX (>20), large intraday swings
    - CHOPPY: Conflicting signals, whipsaws

    This classifier determines which bot (2.0 Iron Condor or 3.0 Momentum)
    should be active at any given time.
    """

    def __init__(self, config):
        """
        Initialize regime classifier

        Args:
            config: Config object with regime parameters
        """
        self.adx_trending = config.regime_adx_trending
        self.adx_ranging = config.regime_adx_ranging
        self.vix_volatile = config.regime_vix_volatile
        self.atr_percentile_high = config.regime_atr_percentile_high

        self.logger = logging.getLogger(__name__)
        self.logger.info(
            f"RegimeClassifier initialized: "
            f"ADX trending={self.adx_trending}, ranging={self.adx_ranging}, "
            f"VIX volatile={self.vix_volatile}"
        )

    def classify(self, market_data: Dict) -> MarketRegime:
        """
        Main classification logic

        Args:
            market_data: Dict containing:
                - adx: ADX value (0-100)
                - vix: VIX value
                - atr_percentile: ATR percentile (0-100)
                - di_plus: DI+ value
                - di_minus: DI- value
                - spot: Current spot price

        Returns:
            MarketRegime enum
        """
        adx = market_data.get('adx', 0)
        vix = market_data.get('vix', 0)
        atr_percentile = market_data.get('atr_percentile', 0)
        di_plus = market_data.get('di_plus', 0)
        di_minus = market_data.get('di_minus', 0)

        # Calculate directional clarity
        directional_diff = abs(di_plus - di_minus)

        # PRIORITY 1: VOLATILE - High uncertainty
        if vix > self.vix_volatile or atr_percentile > self.atr_percentile_high:
            self.logger.debug(
                f"Regime: VOLATILE (VIX={vix:.2f}, ATR%={atr_percentile:.1f})"
            )
            return MarketRegime.VOLATILE

        # PRIORITY 2: TRENDING - Strong directional movement
        if adx > self.adx_trending and vix < self.vix_volatile:
            if directional_diff > 10:  # Clear direction
                self.logger.debug(
                    f"Regime: TRENDING (ADX={adx:.2f}, DI diff={directional_diff:.2f})"
                )
                return MarketRegime.TRENDING

        # PRIORITY 3: RANGING - Sideways movement
        if adx < self.adx_ranging and vix < self.vix_volatile:
            if directional_diff < 5:  # No clear direction
                self.logger.debug(
                    f"Regime: RANGING (ADX={adx:.2f}, DI diff={directional_diff:.2f})"
                )
                return MarketRegime.RANGING

        # PRIORITY 4: CHOPPY - Mixed signals
        self.logger.debug(
            f"Regime: CHOPPY (ADX={adx:.2f}, VIX={vix:.2f}, conflicting signals)"
        )
        return MarketRegime.CHOPPY

    def get_regime_confidence(self, market_data: Dict) -> float:
        """
        Returns confidence score 0-1 for current regime classification

        Higher confidence = clearer regime signals
        Lower confidence = regime transition or ambiguity

        Args:
            market_data: Same as classify()

        Returns:
            Confidence score (0.0 - 1.0)
        """
        adx = market_data.get('adx', 0)
        vix = market_data.get('vix', 0)
        di_plus = market_data.get('di_plus', 0)
        di_minus = market_data.get('di_minus', 0)
        atr_percentile = market_data.get('atr_percentile', 0)

        regime = self.classify(market_data)
        confidence = 0.5  # Base confidence

        if regime == MarketRegime.TRENDING:
            # Confidence increases with ADX strength and directional clarity
            adx_confidence = min((adx - self.adx_trending) / 20, 1.0)
            directional_confidence = min(abs(di_plus - di_minus) / 20, 1.0)
            confidence = 0.3 + 0.35 * adx_confidence + 0.35 * directional_confidence

        elif regime == MarketRegime.RANGING:
            # Confidence increases with low ADX and stable VIX
            adx_confidence = max(1.0 - (adx / self.adx_ranging), 0)
            vix_confidence = max(1.0 - (vix / self.vix_volatile), 0)
            confidence = 0.3 + 0.35 * adx_confidence + 0.35 * vix_confidence

        elif regime == MarketRegime.VOLATILE:
            # Confidence increases with high VIX or ATR
            vix_confidence = min((vix - self.vix_volatile) / 10, 1.0)
            atr_confidence = min(atr_percentile / 100, 1.0)
            confidence = 0.3 + 0.35 * vix_confidence + 0.35 * atr_confidence

        elif regime == MarketRegime.CHOPPY:
            # Low confidence for choppy markets
            confidence = 0.3

        return max(0.0, min(1.0, confidence))

    def get_regime_description(self, regime: MarketRegime) -> str:
        """
        Get human-readable description of regime

        Args:
            regime: MarketRegime enum

        Returns:
            Description string
        """
        descriptions = {
            MarketRegime.TRENDING: "Strong directional movement - favor momentum strategies",
            MarketRegime.RANGING: "Sideways consolidation - favor range-bound strategies",
            MarketRegime.VOLATILE: "High uncertainty and wide swings - reduce exposure",
            MarketRegime.CHOPPY: "Mixed signals and whipsaws - stay cautious",
            MarketRegime.UNKNOWN: "Insufficient data for classification"
        }
        return descriptions.get(regime, "Unknown regime")

    def should_trade_momentum(self, market_data: Dict) -> Tuple[bool, str]:
        """
        Quick check: Should momentum bot (Bot 3.0) trade?

        Args:
            market_data: Same as classify()

        Returns:
            (should_trade: bool, reason: str)
        """
        regime = self.classify(market_data)
        confidence = self.get_regime_confidence(market_data)

        if regime == MarketRegime.TRENDING:
            if confidence >= 0.6:
                return True, f"Trending regime with {confidence:.0%} confidence"
            else:
                return False, f"Trending but low confidence ({confidence:.0%})"

        elif regime == MarketRegime.VOLATILE:
            return False, "Volatile market - momentum unreliable"

        elif regime == MarketRegime.RANGING:
            return False, "Ranging market - use Iron Condor instead"

        else:  # CHOPPY
            return False, "Choppy market - stay in cash"

    def should_trade_iron_condor(self, market_data: Dict) -> Tuple[bool, str]:
        """
        Quick check: Should Iron Condor bot (Bot 2.0) trade?

        Args:
            market_data: Same as classify()

        Returns:
            (should_trade: bool, reason: str)
        """
        regime = self.classify(market_data)
        confidence = self.get_regime_confidence(market_data)

        if regime == MarketRegime.RANGING:
            if confidence >= 0.6:
                return True, f"Ranging regime with {confidence:.0%} confidence"
            else:
                return False, f"Ranging but low confidence ({confidence:.0%})"

        elif regime == MarketRegime.VOLATILE:
            # Iron Condor can work in volatile markets with wider strikes
            if confidence >= 0.7:
                return True, f"Volatile but manageable ({confidence:.0%} confidence)"
            else:
                return False, "Too volatile for Iron Condor"

        elif regime == MarketRegime.TRENDING:
            return False, "Trending market - use momentum instead"

        else:  # CHOPPY
            return False, "Choppy market - stay in cash"
