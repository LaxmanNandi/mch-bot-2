"""
Market constants and enumerations for MCH Bot 3.0
"""

from enum import Enum


class MarketRegime(Enum):
    """Market regime classifications"""
    TRENDING = "trending"
    RANGING = "ranging"
    VOLATILE = "volatile"
    CHOPPY = "choppy"
    UNKNOWN = "unknown"


class OptionType(Enum):
    """Option types"""
    CALL = "CE"
    PUT = "PE"


class OrderSide(Enum):
    """Order sides"""
    BUY = "BUY"
    SELL = "SELL"


class PositionStatus(Enum):
    """Position statuses"""
    PENDING = "pending"
    ACTIVE = "active"
    PARTIAL_EXIT = "partial_exit"
    CLOSED = "closed"
    FAILED = "failed"


class BrokerMode(Enum):
    """Broker execution modes"""
    PAPER = "paper"
    KITE = "kite"


class TelegramMode(Enum):
    """Telegram override modes"""
    CONFIRM = "CONFIRM"  # Require manual confirmation
    AUTO = "AUTO"        # Fully automated
    MANUAL = "MANUAL"    # All orders manual


# Market constants
NIFTY_LOT_SIZE = 75
BANKNIFTY_LOT_SIZE = 15
STRIKE_STEP_NIFTY = 50
STRIKE_STEP_BANKNIFTY = 100

# Time constants
SECONDS_IN_DAY = 86400
MARKET_OPEN_IST = "09:15"
MARKET_CLOSE_IST = "15:30"

# Risk constants
MIN_CONFIDENCE_SCORE = 70  # Minimum confidence to trade
MAX_POSITION_COUNT = 2     # Maximum concurrent positions
