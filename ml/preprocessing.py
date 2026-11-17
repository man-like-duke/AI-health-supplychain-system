"""Validation, feature derivation, and reproducible sklearn preprocessing.

Preprocessing is fitted inside the model pipeline on training data only.
Inference reuses that same fitted pipeline, so there is no separate scaler
or encoder that can drift out of sync.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.impute import SimpleImputer
from sklearn.model_selection import StratifiedGroupKFold
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from ml.schema import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    RAW_NUMERIC_COLUMNS,
    TARGET_COLUMN,
)
from src.config import DAYS_PER_MONTH
from src.errors import DataValidationError

NUMERIC_PIPELINE_STEPS = (
    ("imputer", SimpleImputer(strategy="median")),
    ("scaler", StandardScaler()),
)

CATEGORICAL_PIPELINE_STEPS = (
    ("imputer", SimpleImputer(strategy="most_frequent")),
    (
        "encoder",
        OneHotEncoder(handle_unknown="ignore", sparse_output=False),
    ),
)


def derive_features(df: pd.DataFrame) -> pd.DataFrame:
    """Validate raw inputs and add the derived coverage features.

    ``avg_daily_consumption`` and ``days_of_stock`` are recomputed from
    the raw inputs every time. That keeps training and inference on one
    definition and matches the deterministic 30-day month in
    ``src/config.py``.
    """
    if df.empty:
        raise DataValidationError("Input data is empty.")

    required = set(RAW_NUMERIC_COLUMNS) | set(CATEGORICAL_FEATURES)
    missing = required - set(df.columns)
    if missing:
        raise DataValidationError(
            f"Missing required columns: {sorted(missing)}"
        )

    result = df.copy()

    for column in RAW_NUMERIC_COLUMNS:
        try:
            result[column] = pd.to_numeric(result[column], errors="raise")
        except (TypeError, ValueError) as exc:
            raise DataValidationError(
                f"{column} must contain numeric values."
            ) from exc

    if result[list(RAW_NUMERIC_COLUMNS)].isna().any().any():
        raise DataValidationError(
            "Numeric model inputs cannot contain missing values."
        )

    for column in CATEGORICAL_FEATURES:
        result[column] = result[column].astype("string").str.strip()

    if result[list(CATEGORICAL_FEATURES)].isna().any().any():
        raise DataValidationError(
            "Facility, region, and medicine cannot be missing."
        )

    if (result[list(CATEGORICAL_FEATURES)] == "").any().any():
        raise DataValidationError(
            "Facility, region, and medicine cannot be blank."
        )

    if (result["current_stock"] < 0).any():
        raise DataValidationError("current_stock cannot be negative.")

    if (result["monthly_consumption"] <= 0).any():
        raise DataValidationError(
            "monthly_consumption must be greater than zero."
        )

    if (result["lead_time_days"] <= 0).any():
        raise DataValidationError("lead_time_days must be greater than zero.")

    if (result["expiry_days"] < 0).any():
        raise DataValidationError("expiry_days cannot be negative.")

    if (result["recent_consumption_trend"] <= 0).any():
        raise DataValidationError(
            "recent_consumption_trend must be greater than zero."
        )

    if (result["replenishment_frequency"] < 0).any():
        raise DataValidationError(
            "replenishment_frequency cannot be negative."
        )

    if (result["historical_stockout_count"] < 0).any():
        raise DataValidationError(
            "historical_stockout_count cannot be negative."
        )

    if not result["month"].between(1, 12).all():
        raise DataValidationError("month must be between 1 and 12.")

    result["avg_daily_consumption"] = (
        result["monthly_consumption"] / DAYS_PER_MONTH
    )
    result["days_of_stock"] = (
        result["current_stock"] / result["avg_daily_consumption"]
    )

    return result


def validate_training_frame(df: pd.DataFrame) -> pd.DataFrame:
    """Validate features and the binary target, returning derived data."""
    result = derive_features(df)

    if TARGET_COLUMN not in result.columns:
        raise DataValidationError(f"Missing required column: {TARGET_COLUMN}")

    target = pd.to_numeric(result[TARGET_COLUMN], errors="coerce")

    if target.isna().any():
        raise DataValidationError(
            f"{TARGET_COLUMN} cannot contain missing values."
        )

    if not set(target.unique()).issubset({0, 1}):
        raise DataValidationError(
            f"{TARGET_COLUMN} must contain only 0 and 1."
        )

    result[TARGET_COLUMN] = target.astype(int)
    return result


def build_preprocessor() -> ColumnTransformer:
    """Build the unfitted preprocessing transformer."""
    numeric_pipeline = Pipeline(steps=list(NUMERIC_PIPELINE_STEPS))
    categorical_pipeline = Pipeline(steps=list(CATEGORICAL_PIPELINE_STEPS))

    return ColumnTransformer(
        transformers=[
            ("numeric", numeric_pipeline, list(NUMERIC_FEATURES)),
            (
                "categorical",
                categorical_pipeline,
                list(CATEGORICAL_FEATURES),
            ),
        ],
        remainder="drop",
        verbose_feature_names_out=False,
    )


def build_model_pipeline(estimator) -> Pipeline:
    """Combine preprocessing and a classifier into one fitted artifact."""
    return Pipeline(
        steps=[
            ("preprocessor", build_preprocessor()),
            ("classifier", estimator),
        ]
    )


def split_train_validation_test(
    df: pd.DataFrame,
    seed: int = 42,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Return 60/20/20 train, validation, and test splits.

    Splits are stratified by target and grouped by facility/medicine pair,
    so the same pair never appears in more than one split. The validation
    split selects the model and threshold; the test split is touched once
    for the final held-out estimate.
    """
    validated = validate_training_frame(df)

    groups = (
        validated["facility"].astype(str)
        + " | "
        + validated["medicine"].astype(str)
    )

    if groups.nunique() < 3:
        raise DataValidationError(
            "At least three facility/medicine pairs are required."
        )

    splitter = StratifiedGroupKFold(
        n_splits=5,
        shuffle=True,
        random_state=seed,
    )
    folds = list(
        splitter.split(
            validated[list(FEATURE_COLUMNS)],
            validated[TARGET_COLUMN],
            groups,
        )
    )

    test_index = folds[0][1]
    validation_index = folds[1][1]
    train_index = np.concatenate([fold[1] for fold in folds[2:]])

    train = validated.iloc[train_index].reset_index(drop=True)
    validation = validated.iloc[validation_index].reset_index(drop=True)
    test = validated.iloc[test_index].reset_index(drop=True)

    for name, split in (
        ("training", train),
        ("validation", validation),
        ("test", test),
    ):
        if split[TARGET_COLUMN].nunique() < 2:
            raise DataValidationError(
                f"The {name} split must contain both target classes."
            )

    return train, validation, test
