import pandas as pd

TARGET_COVERAGE_MULTIPLIER = 2.0

RISK_PRIORITY = {
    "CRITICAL": 1,
    "HIGH": 2,
    "MEDIUM": 3,
    "LOW": 4,
}


def find_redistribution_opportunities(df: pd.DataFrame) -> pd.DataFrame:
    """
    Identify and rank potential redistribution opportunities.

    The algorithm:
    1. Finds HIGH/CRITICAL destinations.
    2. Calculates each destination's target coverage and stock gap.
    3. Finds facilities holding the same medicine.
    4. Protects each source facility's minimum reserve.
    5. Calculates usable source surplus.
    6. Ranks viable sources for each destination.

    These are decision-support candidates only.
    Human validation is always required.
    """
    opportunities = []

    for _, destination in df.iterrows():
        if destination["stockout_risk"] not in {"HIGH", "CRITICAL"}:
            continue

        destination_target = (
            destination["lead_time_days"] * TARGET_COVERAGE_MULTIPLIER
        )

        destination_gap = max(
            destination_target - destination["days_of_stock"],
            0,
        )

        if destination_gap <= 0:
            continue

        for _, source in df.iterrows():
            # A facility cannot redistribute stock to itself.
            if source["facility"] == destination["facility"]:
                continue

            # Only the same medicine can be redistributed.
            if source["medicine"] != destination["medicine"]:
                continue

            # Protect the source facility's own reserve.
            source_reserve = (
                source["lead_time_days"] * TARGET_COVERAGE_MULTIPLIER
            )

            source_surplus = (
                source["days_of_stock"] - source_reserve
            )

            # Do not recommend transfers that would compromise the source.
            if source_surplus <= 0:
                continue

            potential_transfer = min(
                source_surplus,
                destination_gap,
            )

            risk_priority = RISK_PRIORITY[
                destination["stockout_risk"]
            ]

            # Higher score = better candidate.
            #
            # We prioritize:
            # 1. More urgent destination risk.
            # 2. Larger usable source surplus.
            # 3. Sources whose stock expires sooner.
            recommendation_score = (
                (5 - risk_priority) * 100
                + min(source_surplus, 100)
                + max(0, 100 - source["expiry_days"]) * 0.1
            )

            opportunities.append(
                {
                    "medicine": destination["medicine"],
                    "source_facility": source["facility"],
                    "destination_facility": destination["facility"],
                    "source_days_of_stock": round(
                        source["days_of_stock"], 1
                    ),
                    "source_reserve_days": round(
                        source_reserve, 1
                    ),
                    "source_surplus_days": round(
                        source_surplus, 1
                    ),
                    "destination_days_of_stock": round(
                        destination["days_of_stock"], 1
                    ),
                    "destination_target_days": round(
                        destination_target, 1
                    ),
                    "destination_gap_days": round(
                        destination_gap, 1
                    ),
                    "potential_transfer_days": round(
                        potential_transfer, 1
                    ),
                    "source_expiry_days": source["expiry_days"],
                    "destination_stockout_risk": destination[
                        "stockout_risk"
                    ],
                    "risk_priority": risk_priority,
                    "recommendation_score": round(
                        recommendation_score, 2
                    ),
                    "requires_human_review": True,
                }
            )

    result = pd.DataFrame(opportunities)

    if result.empty:
        return result

    # Highest-priority recommendations first.
    result = result.sort_values(
        by=[
            "risk_priority",
            "recommendation_score",
        ],
        ascending=[
            True,
            False,
        ],
    )

    return result.reset_index(drop=True)