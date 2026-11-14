import pandas as pd

from src.config import (
    DAYS_PER_MONTH,
    EXPIRY_WATCH_BAND_DAYS,
    STOCKOUT_HIGH_MULTIPLIER,
    STOCKOUT_MEDIUM_MULTIPLIER,
    TARGET_COVERAGE_MULTIPLIER,
)


def calculate_days_of_stock(
    current_stock: float,
    monthly_consumption: float,
) -> float:
    """Calculate how many days the current inventory can cover."""
    if monthly_consumption <= 0:
        raise ValueError("monthly_consumption must be greater than zero.")

    average_daily_consumption = monthly_consumption / DAYS_PER_MONTH

    return current_stock / average_daily_consumption


def classify_stockout_risk(
    days_of_stock: float,
    lead_time_days: float,
) -> str:
    """Classify stockout risk using transparent prototype thresholds."""
    if lead_time_days < 0:
        raise ValueError("lead_time_days cannot be negative.")

    if days_of_stock < lead_time_days:
        return "CRITICAL"

    if days_of_stock < lead_time_days * STOCKOUT_HIGH_MULTIPLIER:
        return "HIGH"

    if days_of_stock < lead_time_days * STOCKOUT_MEDIUM_MULTIPLIER:
        return "MEDIUM"

    return "LOW"


def classify_expiry_risk(
    days_of_stock: float,
    expiry_days: float,
) -> str:
    """Classify the risk that inventory may outlast its expiry window.

    HIGH: current stock will last longer than the remaining shelf life.
    MEDIUM: stock is consumed before expiry, but the margin is smaller
    than the configured watch band.
    LOW: there is a comfortable margin, or there is no stock to expire.
    """
    if expiry_days < 0:
        raise ValueError("expiry_days cannot be negative.")

    if days_of_stock <= 0:
        return "LOW"

    if expiry_days < days_of_stock:
        return "HIGH"

    if expiry_days - days_of_stock < EXPIRY_WATCH_BAND_DAYS:
        return "MEDIUM"

    return "LOW"


def analyze_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate inventory coverage and risk classifications."""
    result = df.copy()

    result["days_of_stock"] = result["current_stock"] / (
        result["monthly_consumption"] / DAYS_PER_MONTH
    )

    result["target_days"] = (
        result["lead_time_days"] * TARGET_COVERAGE_MULTIPLIER
    )

    result["stockout_risk"] = result.apply(
        lambda row: classify_stockout_risk(
            row["days_of_stock"],
            row["lead_time_days"],
        ),
        axis=1,
    )

    result["expiry_risk"] = result.apply(
        lambda row: classify_expiry_risk(
            row["days_of_stock"],
            row["expiry_days"],
        ),
        axis=1,
    )

    return result
