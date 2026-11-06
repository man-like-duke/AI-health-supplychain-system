import pandas as pd


def build_decision_summary(
    inventory: pd.DataFrame,
    recommendations: pd.DataFrame,
) -> dict:
    """
    Build a structured decision-support summary.

    This layer summarizes deterministic analytical results.
    It does not make autonomous operational decisions.
    """

    critical_items = inventory[
        inventory["stockout_risk"] == "CRITICAL"
    ]

    high_items = inventory[
        inventory["stockout_risk"] == "HIGH"
    ]

    expiry_items = inventory[
        inventory["expiry_risk"].isin({"HIGH", "MEDIUM"})
    ]

    top_recommendations = recommendations.head(5)

    recommendation_list = []

    for _, row in top_recommendations.iterrows():
        recommendation_list.append(
            {
                "medicine": row["medicine"],
                "source_facility": row["source_facility"],
                "destination_facility": row[
                    "destination_facility"
                ],
                "destination_stockout_risk": row[
                    "destination_stockout_risk"
                ],
                "destination_days_of_stock": row[
                    "destination_days_of_stock"
                ],
                "destination_gap_days": row[
                    "destination_gap_days"
                ],
                "potential_transfer_days": row[
                    "potential_transfer_days"
                ],
                "source_surplus_days": row[
                    "source_surplus_days"
                ],
                "source_expiry_days": row[
                    "source_expiry_days"
                ],
                "requires_human_review": bool(
                    row["requires_human_review"]
                ),
            }
        )

    return {
        "summary": {
            "facilities_analyzed": int(
                inventory["facility"].nunique()
            ),
            "medicine_facility_records": len(inventory),
            "critical_stockout_items": len(critical_items),
            "high_stockout_items": len(high_items),
            "expiry_risk_items": len(expiry_items),
            "redistribution_candidates": len(recommendations),
        },
        "critical_items": critical_items[
            [
                "facility",
                "medicine",
                "days_of_stock",
                "lead_time_days",
                "expiry_days",
                "stockout_risk",
                "expiry_risk",
            ]
        ].to_dict(orient="records"),
        "redistribution_recommendations": recommendation_list,
        "governance": {
            "data_type": "synthetic",
            "autonomous_action": False,
            "human_review_required": True,
            "note": (
                "Recommendations are analytical decision-support "
                "candidates and must be validated by an authorized "
                "health-program or supply-chain professional."
            ),
        },
    }