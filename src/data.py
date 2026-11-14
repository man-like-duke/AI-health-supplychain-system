import os
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

from src.errors import DataValidationError

load_dotenv()

DATA_PATH = Path(
    os.getenv(
        "FACILITY_DATA_PATH",
        Path(__file__).resolve().parent.parent / "data" / "facilities.csv",
    )
)


REQUIRED_COLUMNS = {
    "facility",
    "region",
    "medicine",
    "current_stock",
    "monthly_consumption",
    "lead_time_days",
    "expiry_days",
}

NUMERIC_COLUMNS = (
    "current_stock",
    "monthly_consumption",
    "lead_time_days",
    "expiry_days",
)

TEXT_COLUMNS = ("facility", "region", "medicine")


def load_facility_data(path: Path = DATA_PATH) -> pd.DataFrame:
    """Load and validate the synthetic facility inventory dataset.

    Validation is intentionally strict: a missing or malformed value must
    never be silently treated as healthy inventory.
    """
    path = Path(path)

    if not path.exists():
        raise DataValidationError(f"Dataset not found: {path}")

    try:
        df = pd.read_csv(path)
    except pd.errors.EmptyDataError as exc:
        raise DataValidationError("The facility dataset is empty.") from exc

    df.columns = [column.strip() for column in df.columns]

    missing_columns = REQUIRED_COLUMNS - set(df.columns)

    if missing_columns:
        raise DataValidationError(
            f"Missing required columns: {sorted(missing_columns)}"
        )

    if df.empty:
        raise DataValidationError("The facility dataset is empty.")

    for column in TEXT_COLUMNS:
        df[column] = df[column].astype("string").str.strip()

    for column in NUMERIC_COLUMNS:
        try:
            df[column] = pd.to_numeric(df[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise DataValidationError(
                f"{column} must contain numeric values."
            ) from exc

    missing_values = df[list(REQUIRED_COLUMNS)].isna()
    if missing_values.any().any():
        affected = sorted(
            missing_values.columns[missing_values.any()].tolist()
        )
        raise DataValidationError(f"Missing values found in: {affected}")

    if (df[list(TEXT_COLUMNS)] == "").any().any():
        raise DataValidationError(
            "Facility, region, and medicine values cannot be blank."
        )

    if (df[list(NUMERIC_COLUMNS)] < 0).any().any():
        raise DataValidationError(
            "Numeric inventory values cannot be negative."
        )

    if (df["monthly_consumption"] == 0).any():
        raise DataValidationError(
            "monthly_consumption must be greater than zero."
        )

    if (df["lead_time_days"] == 0).any():
        raise DataValidationError("lead_time_days must be greater than zero.")

    duplicate_rows = df.duplicated(subset=["facility", "medicine"])
    if duplicate_rows.any():
        raise DataValidationError("Duplicate facility/medicine rows found.")

    return df
