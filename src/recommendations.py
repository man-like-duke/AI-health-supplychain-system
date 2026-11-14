"""Identify and rank potential redistribution opportunities.

The algorithm is deliberately transparent:

1. Find HIGH/CRITICAL destinations with a coverage gap.
2. Protect every source facility's own reserve.
3. Rank viable sources by gap coverage, surplus cushion, and expiry urgency.
4. Allocate transfers greedily so neither a destination gap nor a source
   surplus is promised more than once.

These are decision-support candidates only. Human validation is always
required.
"""

import pandas as pd

from src.config import (
    COVERAGE_WEIGHT,
    EXPIRY_SCORE_HORIZON_DAYS,
    EXPIRY_WEIGHT,
    MIN_TRANSFER_DAYS,
    RISK_PRIORITY,
    SURPLUS_WEIGHT,
    TARGET_COVERAGE_MULTIPLIER,
)

REQUIRED_COLUMNS = {
    "facility",
    "medicine",
    "days_of_stock",
    "lead_time_days",
    "expiry_days",
    "stockout_risk",
}


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _score_source(
    expiry_days: float,
    surplus_days: float,
    destination_gap_days: float,
) -> float:
    """Score a source for a single destination.

    The score is a weighted combination of:
    - coverage: how much of the destination gap this source can fill,
    - cushion: whether the source has surplus beyond twice the gap,
    - expiry urgency: stock expiring sooner is preferred to avoid waste.
    """
    if destination_gap_days <= 0:
        return 0.0

    coverage = _clamp(
        min(surplus_days, destination_gap_days) / destination_gap_days
    )
    cushion = _clamp(surplus_days / (2.0 * destination_gap_days))
    expiry_urgency = _clamp(1.0 - (expiry_days / EXPIRY_SCORE_HORIZON_DAYS))

    return round(
        COVERAGE_WEIGHT * coverage
        + SURPLUS_WEIGHT * cushion
        + EXPIRY_WEIGHT * expiry_urgency,
        4,
    )


def find_redistribution_opportunities(df: pd.DataFrame) -> pd.DataFrame:
    """Identify and rank potential redistribution opportunities."""
    missing_columns = REQUIRED_COLUMNS - set(df.columns)
    if missing_columns:
        raise ValueError(
            f"Missing required columns: {sorted(missing_columns)}"
        )

    if df.empty:
        return pd.DataFrame()

    if df["stockout_risk"].isna().any():
        raise ValueError("stockout_risk cannot contain missing values.")

    unknown_risks = set(df["stockout_risk"].unique()) - set(RISK_PRIORITY)
    if unknown_risks:
        raise ValueError(
            f"Unknown stockout_risk values: {sorted(unknown_risks)}"
        )

    if df.duplicated(subset=["facility", "medicine"]).any():
        raise ValueError("Duplicate facility/medicine rows found.")

    working = df.copy()

    working["tmp_source_reserve_days"] = (
        working["lead_time_days"] * TARGET_COVERAGE_MULTIPLIER
    )
    working["tmp_source_surplus_days"] = (
        working["days_of_stock"] - working["tmp_source_reserve_days"]
    )

    sources = working[working["tmp_source_surplus_days"] > 0].copy()

    remaining_surplus = {
        (row.facility, row.medicine): float(row.tmp_source_surplus_days)
        for row in sources.itertuples(index=False)
    }

    if not remaining_surplus:
        return pd.DataFrame()

    sources_by_medicine = {
        medicine: group
        for medicine, group in sources.groupby("medicine", sort=False)
    }

    destinations = working[
        working["stockout_risk"].isin({"HIGH", "CRITICAL"})
    ].copy()

    if destinations.empty:
        return pd.DataFrame()

    destinations["tmp_destination_target_days"] = (
        destinations["lead_time_days"] * TARGET_COVERAGE_MULTIPLIER
    )
    destinations["tmp_destination_gap_days"] = (
        destinations["tmp_destination_target_days"]
        - destinations["days_of_stock"]
    ).clip(lower=0)

    destinations = destinations[
        destinations["tmp_destination_gap_days"] > 0
    ].copy()

    if destinations.empty:
        return pd.DataFrame()

    destinations["tmp_risk_priority"] = destinations["stockout_risk"].map(
        RISK_PRIORITY
    )
    destinations = destinations.sort_values(
        by=["tmp_risk_priority", "tmp_destination_gap_days"],
        ascending=[True, False],
    )

    opportunities = []

    for destination in destinations.itertuples(index=False):
        original_gap = float(destination.tmp_destination_gap_days)
        remaining_gap = original_gap

        candidates = sources_by_medicine.get(destination.medicine)
        if candidates is None:
            continue

        scored_candidates = []

        for source in candidates.itertuples(index=False):
            if source.facility == destination.facility:
                continue

            key = (source.facility, source.medicine)
            surplus = remaining_surplus.get(key, 0.0)

            if surplus <= 0:
                continue

            scored_candidates.append(
                (
                    _score_source(
                        expiry_days=float(source.expiry_days),
                        surplus_days=surplus,
                        destination_gap_days=original_gap,
                    ),
                    source,
                    surplus,
                )
            )

        # Higher score first; facility name breaks ties deterministically.
        scored_candidates.sort(key=lambda item: (-item[0], item[1].facility))

        for score, source, surplus in scored_candidates:
            if remaining_gap <= 0:
                break

            # Do not recommend more stock than can be consumed before the
            # source batch expires.
            expiry_cap = max(0.0, float(source.expiry_days))
            transfer = min(surplus, remaining_gap, expiry_cap)
            if transfer < MIN_TRANSFER_DAYS:
                continue

            key = (source.facility, source.medicine)
            remaining_surplus[key] = surplus - transfer
            remaining_gap -= transfer

            opportunities.append(
                {
                    "medicine": destination.medicine,
                    "source_facility": source.facility,
                    "destination_facility": destination.facility,
                    "source_days_of_stock": round(
                        float(source.days_of_stock), 1
                    ),
                    "source_reserve_days": round(
                        float(source.tmp_source_reserve_days), 1
                    ),
                    "source_surplus_days": round(surplus, 1),
                    "source_remaining_surplus_days": round(
                        remaining_surplus[key], 1
                    ),
                    "destination_days_of_stock": round(
                        float(destination.days_of_stock), 1
                    ),
                    "destination_target_days": round(
                        float(destination.tmp_destination_target_days), 1
                    ),
                    "destination_gap_days": round(original_gap, 1),
                    "destination_remaining_gap_days": round(remaining_gap, 1),
                    "potential_transfer_days": round(transfer, 1),
                    "source_expiry_days": float(source.expiry_days),
                    "destination_stockout_risk": destination.stockout_risk,
                    "risk_priority": int(destination.tmp_risk_priority),
                    "recommendation_score": score,
                    "requires_human_review": True,
                }
            )

    result = pd.DataFrame(opportunities)

    if result.empty:
        return result

    result = result.sort_values(
        by=["risk_priority", "recommendation_score"],
        ascending=[True, False],
    )

    return result.reset_index(drop=True)
