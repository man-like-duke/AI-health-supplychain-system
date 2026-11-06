import pandas as pd


DAYS_PER_MONTH = 30


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

    if days_of_stock < lead_time_days * 1.5:
        return "HIGH"

    if days_of_stock < lead_time_days * 2:
        return "MEDIUM"

    return "LOW"


def classify_expiry_risk(
    days_of_stock: float,
    expiry_days: float,
) -> str:
    """Classify the risk that inventory may outlast its expiry window."""
    if expiry_days < 0:
        raise ValueError("expiry_days cannot be negative.")

    if expiry_days < days_of_stock:
        return "HIGH"

    if expiry_days < days_of_stock * 1.5:
        return "MEDIUM"

    return "LOW"


def analyze_inventory(df: pd.DataFrame) -> pd.DataFrame:
    """Calculate inventory coverage and risk classifications."""
    result = df.copy()

    result["days_of_stock"] = (
        result["current_stock"]
        / (result["monthly_consumption"] / DAYS_PER_MONTH)
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