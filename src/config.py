"""Central configuration for the analysis pipeline.

Keeping the prototype's thresholds and weights in one module makes its
assumptions explicit and easy to tune or review.
"""

# Inventory coverage
DAYS_PER_MONTH = 30

# Risk thresholds, expressed as multiples of lead time.
STOCKOUT_HIGH_MULTIPLIER = 1.5
STOCKOUT_MEDIUM_MULTIPLIER = 2.0

# A destination is expected to hold at least this many lead times of cover.
# The same multiplier protects a source facility's own reserve.
TARGET_COVERAGE_MULTIPLIER = 2.0

# Expiry "watch band": when the remaining shelf life exceeds current
# coverage by less than this many days, the item is flagged MEDIUM.
EXPIRY_WATCH_BAND_DAYS = 30.0

# Recommendation generation
TOP_RECOMMENDATIONS = 5
MIN_TRANSFER_DAYS = 1.0

RISK_PRIORITY = {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 3,
    "LOW": 4,
}

# Recommendation scoring weights. They must sum to 1.0.
COVERAGE_WEIGHT = 0.5
SURPLUS_WEIGHT = 0.3
EXPIRY_WEIGHT = 0.2

# Expiry urgency is measured against this horizon. Stock expiring within
# the horizon scores higher, encouraging use-before-expiry transfers.
EXPIRY_SCORE_HORIZON_DAYS = 365.0
