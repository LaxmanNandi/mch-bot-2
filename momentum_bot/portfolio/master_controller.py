"""
Master Portfolio Controller for MCH Trading System

CRITICAL MODULE - Gemini Fix #2
Regime-based strategy selector
Only ONE bot active at a time (Bot 2.0 Iron Condor OR Bot 3.0 Momentum)
PREVENTS CROSS-BOT CONFLICTS
"""

from typing import Dict
import logging
from datetime import datetime
from momentum_bot.core.constants import MarketRegime
from momentum_bot.signals.regime_classifier import RegimeClassifier


class MasterPortfolioController:
    """
    Master controller for entire portfolio strategy selection

    Key Responsibilities:
    1. Classify market regime (via RegimeClassifier)
    2. Decide which bot should be active
    3. Ensure ONLY ONE bot trades at a time
    4. Log regime changes and strategy switches
    5. Provide clear reasoning for decisions
    """

    def __init__(self, regime_classifier: RegimeClassifier, logger=None):
        """
        Initialize master controller

        Args:
            regime_classifier: RegimeClassifier instance
            logger: Optional logger instance
        """
        self.regime_classifier = regime_classifier
        self.logger = logger or logging.getLogger(__name__)

        self.current_regime = None
        self.active_strategy = None
        self.regime_change_time = None
        self.regime_stability_count = 0  # Consecutive bars in same regime

        self.logger.info("=" * 80)
        self.logger.info("MASTER PORTFOLIO CONTROLLER INITIALIZED")
        self.logger.info("=" * 80)
        self.logger.info("This controller ensures only ONE bot trades at a time")
        self.logger.info("Bot 2.0 (Iron Condor) vs Bot 3.0 (Momentum) conflicts prevented")
        self.logger.info("=" * 80)

    def determine_active_strategy(self, market_data: Dict) -> Dict:
        """
        Determines which bot should be active based on market regime

        Returns:
            {
                'bot_2_iron_condor': bool,
                'bot_3_momentum': bool,
                'regime': MarketRegime,
                'confidence': float,
                'reason': str,
                'stability': int  # bars in same regime
            }
        """

        # Classify current regime
        regime = self.regime_classifier.classify(market_data)
        confidence = self.regime_classifier.get_regime_confidence(market_data)

        # Track regime stability
        if regime == self.current_regime:
            self.regime_stability_count += 1
        else:
            self.regime_stability_count = 1
            self.regime_change_time = datetime.now()

        # Decision logic (Gemini's specification)
        if regime == MarketRegime.TRENDING:
            decision = {
                'bot_2_iron_condor': False,  # DISABLED
                'bot_3_momentum': True,      # ACTIVE
                'regime': regime,
                'confidence': confidence,
                'reason': 'Trending market - activate momentum bot (Bot 3.0)',
                'stability': self.regime_stability_count
            }

        elif regime in [MarketRegime.RANGING, MarketRegime.VOLATILE]:
            decision = {
                'bot_2_iron_condor': True,   # ACTIVE
                'bot_3_momentum': False,     # DISABLED
                'regime': regime,
                'confidence': confidence,
                'reason': f'{regime.value.capitalize()} market - activate iron condor bot (Bot 2.0)',
                'stability': self.regime_stability_count
            }

        else:  # CHOPPY or UNKNOWN
            decision = {
                'bot_2_iron_condor': False,  # DISABLED
                'bot_3_momentum': False,     # DISABLED
                'regime': regime,
                'confidence': confidence,
                'reason': f'{regime.value.capitalize()} market - stay in cash (no bot active)',
                'stability': self.regime_stability_count
            }

        # Log regime changes
        if regime != self.current_regime:
            self._log_regime_change(self.current_regime, regime, decision)

        self.current_regime = regime
        self.active_strategy = decision

        return decision

    def _log_regime_change(self, old_regime, new_regime, decision):
        """Log regime changes with detailed information"""
        self.logger.info("")
        self.logger.info("=" * 80)
        self.logger.info("REGIME CHANGE DETECTED")
        self.logger.info("=" * 80)
        self.logger.info(f"Old Regime: {old_regime.value if old_regime else 'None'}")
        self.logger.info(f"New Regime: {new_regime.value}")
        self.logger.info(f"Confidence: {decision['confidence']:.1%}")
        self.logger.info("-" * 80)
        self.logger.info("STRATEGY DECISION:")
        self.logger.info(f"  Bot 2.0 (Iron Condor): {'ACTIVE' if decision['bot_2_iron_condor'] else 'DISABLED'}")
        self.logger.info(f"  Bot 3.0 (Momentum):    {'ACTIVE' if decision['bot_3_momentum'] else 'DISABLED'}")
        self.logger.info(f"  Reason: {decision['reason']}")
        self.logger.info("=" * 80)
        self.logger.info("")

    def should_bot_3_trade(self, market_data: Dict) -> tuple:
        """
        Simple check: Can Bot 3 (Momentum) trade right now?

        Args:
            market_data: Market data dict

        Returns:
            (can_trade: bool, reason: str)
        """
        decision = self.determine_active_strategy(market_data)

        if decision['bot_3_momentum']:
            # Additional stability check - require 2+ consecutive bars
            if decision['stability'] >= 2:
                return True, f"Bot 3 active - {decision['reason']} (stable for {decision['stability']} bars)"
            else:
                return False, f"Regime just changed - waiting for stability (1/{2} bars)"
        else:
            return False, f"Bot 3 disabled - {decision['reason']}"

    def should_bot_2_trade(self, market_data: Dict) -> tuple:
        """
        Simple check: Can Bot 2 (Iron Condor) trade right now?

        Args:
            market_data: Market data dict

        Returns:
            (can_trade: bool, reason: str)
        """
        decision = self.determine_active_strategy(market_data)

        if decision['bot_2_iron_condor']:
            # Additional stability check - require 2+ consecutive bars
            if decision['stability'] >= 2:
                return True, f"Bot 2 active - {decision['reason']} (stable for {decision['stability']} bars)"
            else:
                return False, f"Regime just changed - waiting for stability (1/{2} bars)"
        else:
            return False, f"Bot 2 disabled - {decision['reason']}"

    def get_current_regime(self) -> MarketRegime:
        """Get current market regime"""
        return self.current_regime

    def get_active_bot_name(self) -> str:
        """Get name of currently active bot"""
        if self.active_strategy is None:
            return "None (not initialized)"

        if self.active_strategy['bot_3_momentum']:
            return "Bot 3.0 - Momentum Premium Buyer"
        elif self.active_strategy['bot_2_iron_condor']:
            return "Bot 2.0 - Iron Condor"
        else:
            return "None (cash/sidelines)"

    def get_regime_stability_status(self) -> Dict:
        """
        Get detailed regime stability information

        Returns:
            {
                'regime': MarketRegime,
                'stability_count': int,
                'change_time': datetime,
                'is_stable': bool
            }
        """
        return {
            'regime': self.current_regime,
            'stability_count': self.regime_stability_count,
            'change_time': self.regime_change_time,
            'is_stable': self.regime_stability_count >= 2
        }

    def force_regime_override(self, regime: MarketRegime, reason: str):
        """
        Manual override of regime (for testing or emergency situations)

        Args:
            regime: MarketRegime to force
            reason: Reason for override
        """
        self.logger.warning("")
        self.logger.warning("=" * 80)
        self.logger.warning("MANUAL REGIME OVERRIDE")
        self.logger.warning("=" * 80)
        self.logger.warning(f"Forcing regime to: {regime.value}")
        self.logger.warning(f"Reason: {reason}")
        self.logger.warning("=" * 80)
        self.logger.warning("")

        self.current_regime = regime
        self.regime_stability_count = 10  # Set high stability to allow immediate trading
        self.regime_change_time = datetime.now()

    def get_status_summary(self) -> str:
        """
        Get human-readable status summary

        Returns:
            Multi-line status string
        """
        if self.active_strategy is None:
            return "Master Controller: Not initialized"

        stability_status = "STABLE" if self.regime_stability_count >= 2 else "UNSTABLE"

        summary = f"""
Master Portfolio Controller Status:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
Current Regime:     {self.current_regime.value.upper()}
Regime Confidence:  {self.active_strategy['confidence']:.1%}
Regime Stability:   {stability_status} ({self.regime_stability_count} consecutive bars)

Active Strategy:    {self.get_active_bot_name()}

Bot Status:
  • Bot 2.0 (Iron Condor):  {'✓ ACTIVE' if self.active_strategy['bot_2_iron_condor'] else '✗ DISABLED'}
  • Bot 3.0 (Momentum):     {'✓ ACTIVE' if self.active_strategy['bot_3_momentum'] else '✗ DISABLED'}

Reason: {self.active_strategy['reason']}
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
"""
        return summary
