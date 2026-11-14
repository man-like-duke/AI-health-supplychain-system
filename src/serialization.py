"""Helpers for converting analysis results into API-safe structures."""

import json

import pandas as pd


def dataframe_to_records(df: pd.DataFrame) -> list[dict]:
    """Convert a DataFrame to JSON-native records.

    ``DataFrame.to_dict`` preserves numpy scalar types and can leave
    ``NaN`` values in place, both of which complicate response
    serialization. Round-tripping through ``to_json`` produces plain
    Python types and converts missing values to ``null``.
    """
    if df.empty:
        return []

    return json.loads(df.to_json(orient="records", date_format="iso"))
