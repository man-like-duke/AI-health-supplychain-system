import pandas as pd
import pytest

from src.data import DATA_PATH, load_facility_data
from src.errors import DataValidationError


@pytest.fixture()
def valid_df() -> pd.DataFrame:
    return pd.read_csv(DATA_PATH).astype(object)


def _write(tmp_path, df: pd.DataFrame):
    path = tmp_path / "facilities.csv"
    df.to_csv(path, index=False)
    return path


def test_loads_valid_dataset():
    df = load_facility_data()

    assert len(df) == 52
    assert df["facility"].nunique() == 12
    assert df["medicine"].nunique() == 7
    assert pd.api.types.is_numeric_dtype(df["current_stock"])
    assert pd.api.types.is_numeric_dtype(df["lead_time_days"])


def test_missing_required_column(tmp_path, valid_df):
    path = _write(tmp_path, valid_df.drop(columns=["region"]))

    with pytest.raises(DataValidationError, match="Missing required columns"):
        load_facility_data(path)


def test_empty_file(tmp_path):
    path = tmp_path / "facilities.csv"
    path.write_text("", encoding="utf-8")

    with pytest.raises(DataValidationError, match="empty"):
        load_facility_data(path)


def test_missing_numeric_value(tmp_path, valid_df):
    valid_df.loc[0, "current_stock"] = None
    path = _write(tmp_path, valid_df)

    with pytest.raises(DataValidationError, match="Missing values"):
        load_facility_data(path)


def test_non_numeric_value(tmp_path, valid_df):
    valid_df.loc[0, "current_stock"] = "not-a-number"
    path = _write(tmp_path, valid_df)

    with pytest.raises(DataValidationError, match="numeric"):
        load_facility_data(path)


def test_negative_value(tmp_path, valid_df):
    valid_df.loc[0, "expiry_days"] = -1
    path = _write(tmp_path, valid_df)

    with pytest.raises(DataValidationError, match="negative"):
        load_facility_data(path)


def test_zero_monthly_consumption(tmp_path, valid_df):
    valid_df.loc[0, "monthly_consumption"] = 0
    path = _write(tmp_path, valid_df)

    with pytest.raises(
        DataValidationError,
        match="monthly_consumption",
    ):
        load_facility_data(path)


def test_zero_lead_time(tmp_path, valid_df):
    valid_df.loc[0, "lead_time_days"] = 0
    path = _write(tmp_path, valid_df)

    with pytest.raises(DataValidationError, match="lead_time_days"):
        load_facility_data(path)


def test_duplicate_facility_medicine(tmp_path, valid_df):
    duplicated = pd.concat(
        [valid_df, valid_df.iloc[[0]]],
        ignore_index=True,
    )
    path = _write(tmp_path, duplicated)

    with pytest.raises(DataValidationError, match="Duplicate"):
        load_facility_data(path)


def test_blank_text_value(tmp_path, valid_df):
    valid_df.loc[0, "facility"] = "   "
    path = _write(tmp_path, valid_df)

    with pytest.raises(DataValidationError, match="blank"):
        load_facility_data(path)


def test_missing_file(tmp_path):
    with pytest.raises(DataValidationError, match="not found"):
        load_facility_data(tmp_path / "missing.csv")


def test_text_values_are_stripped(tmp_path, valid_df):
    valid_df.loc[0, "facility"] = "  Abuja Central  "
    path = _write(tmp_path, valid_df)

    df = load_facility_data(path)

    assert df.loc[0, "facility"] == "Abuja Central"


# The empty-CSV path should also surface as our domain error.
def test_empty_dataframe(tmp_path):
    path = tmp_path / "facilities.csv"
    path.write_text(
        ",".join(
            [
                "facility",
                "region",
                "medicine",
                "current_stock",
                "monthly_consumption",
                "lead_time_days",
                "expiry_days",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(DataValidationError, match="empty"):
        load_facility_data(path)
