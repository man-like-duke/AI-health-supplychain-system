from pathlib import Path

import pandas as pd


DATA_PATH = Path(__file__).resolve().parent.parent / "data" / "facilities.csv"


REQUIRED_COLUMNS = {
    "facility",
    "region",
    "medicine",
    "current_stock",
    "monthly_consumption",
    "lead_time_days",
    "expiry_days",
}


def load_facility_data(path: Path = DATA_PATH) -> pd.DataFrame:
    """Load and validate the synthetic facility inventory dataset."""
    df = pd.read_csv(path)

    missing_columns = REQUIRED_COLUMNS - set(df.columns)

    if missing_columns:
        raise ValueError(
            f"Missing required columns: {sorted(missing_columns)}"
        )

    if df.empty:
        raise ValueError("The facility dataset is empty.")

    numeric_columns = [
        "current_stock",
        "monthly_consumption",
        "lead_time_days",
        "expiry_days",
    ]

    for column in numeric_columns:
        if (df[column] < 0).any():
            raise ValueError(f"{column} cannot contain negative values.")

    if (df["monthly_consumption"] == 0).any():
        raise ValueError("monthly_consumption must be greater than zero.")

    return df