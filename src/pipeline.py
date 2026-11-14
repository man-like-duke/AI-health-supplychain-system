"""Composition of the deterministic supply-chain analysis pipeline."""

from copy import deepcopy
from functools import lru_cache
from pathlib import Path

import pandas as pd

from src.data import DATA_PATH, load_facility_data
from src.decisions import build_decision_summary
from src.recommendations import find_redistribution_opportunities
from src.risk import analyze_inventory


@lru_cache(maxsize=4)
def _run_analysis_cached(
    data_path: str,
    modified_time: float,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run the pipeline once per data file version.

    ``modified_time`` is part of the cache key so an updated CSV is picked
    up automatically.
    """
    data = load_facility_data(Path(data_path))
    inventory = analyze_inventory(data)
    recommendations = find_redistribution_opportunities(inventory)
    summary = build_decision_summary(inventory, recommendations)

    return inventory, recommendations, summary


def run_analysis(
    data_path: Path | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    """Run the analysis pipeline, reusing cached results when possible.

    Cached objects are copied before being returned so callers cannot
    accidentally mutate the cached state.
    """
    path = Path(data_path) if data_path is not None else DATA_PATH
    modified_time = path.stat().st_mtime if path.exists() else -1.0

    inventory, recommendations, summary = _run_analysis_cached(
        str(path),
        modified_time,
    )

    return (
        inventory.copy(deep=True),
        recommendations.copy(deep=True),
        deepcopy(summary),
    )


def clear_analysis_cache() -> None:
    """Clear cached analysis results (primarily useful in tests)."""
    _run_analysis_cached.cache_clear()
