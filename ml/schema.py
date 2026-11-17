"""Shared column definitions for the stockout model.

Keeping the schema in one place ensures training, evaluation, and inference
all use exactly the same feature order and preprocessing contract.
"""

from __future__ import annotations

TARGET_COLUMN = "stockout_within_30_days"

IDENTIFIER_COLUMNS = ("facility", "region", "medicine")

# Features observed at prediction time. Nothing here is derived from the
# future outcome window.
NUMERIC_FEATURES = (
    "month",
    "current_stock",
    "monthly_consumption",
    "avg_daily_consumption",
    "recent_consumption_trend",
    "days_of_stock",
    "lead_time_days",
    "historical_stockout_count",
    "replenishment_frequency",
    "expiry_days",
)

DERIVED_NUMERIC_COLUMNS = ("avg_daily_consumption", "days_of_stock")

RAW_NUMERIC_COLUMNS = tuple(
    column
    for column in NUMERIC_FEATURES
    if column not in DERIVED_NUMERIC_COLUMNS
)

CATEGORICAL_FEATURES = IDENTIFIER_COLUMNS

FEATURE_COLUMNS = NUMERIC_FEATURES + CATEGORICAL_FEATURES

# Human-readable column order for the committed synthetic history CSV.
HISTORY_COLUMNS = (
    "facility",
    "region",
    "medicine",
    "month",
    "current_stock",
    "monthly_consumption",
    "recent_consumption_trend",
    "lead_time_days",
    "historical_stockout_count",
    "replenishment_frequency",
    "expiry_days",
    "avg_daily_consumption",
    "days_of_stock",
    TARGET_COLUMN,
)
