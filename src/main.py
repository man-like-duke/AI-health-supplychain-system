from src.data import load_facility_data
from src.risk import analyze_inventory
from src.recommendations import find_redistribution_opportunities
from src.decisions import build_decision_summary


def main():
    data = load_facility_data()
    results = analyze_inventory(data)

    print("\n=== INVENTORY RISK ANALYSIS ===\n")

    columns = [
        "facility",
        "medicine",
        "days_of_stock",
        "stockout_risk",
        "expiry_risk",
    ]

    print(
        results[columns].to_string(index=False)
    )

    opportunities = find_redistribution_opportunities(
        results
    )

    print("\n=== POTENTIAL REDISTRIBUTION OPPORTUNITIES ===\n")

    if opportunities.empty:
        print(
            "No potential redistribution opportunities identified."
        )
    else:
        display_columns = [
            "medicine",
            "source_facility",
            "destination_facility",
            "destination_stockout_risk",
            "source_surplus_days",
            "destination_gap_days",
            "potential_transfer_days",
            "source_expiry_days",
            "requires_human_review",
        ]

        print(
            opportunities[display_columns].to_string(
                index=False
            )
        )

    decision_summary = build_decision_summary(
        results,
        opportunities,
    )

    print("\n=== DECISION SUPPORT SUMMARY ===\n")

    print(
        f"Facilities analyzed: "
        f"{decision_summary['summary']['facilities_analyzed']}"
    )

    print(
        f"Critical stockout items: "
        f"{decision_summary['summary']['critical_stockout_items']}"
    )

    print(
        f"High stockout items: "
        f"{decision_summary['summary']['high_stockout_items']}"
    )

    print(
        f"Expiry-risk items: "
        f"{decision_summary['summary']['expiry_risk_items']}"
    )

    print(
        f"Redistribution candidates: "
        f"{decision_summary['summary']['redistribution_candidates']}"
    )

    print("\nTop recommendations:")

    for recommendation in decision_summary[
        "redistribution_recommendations"
    ]:
        print(
            f"- {recommendation['medicine']}: "
            f"{recommendation['source_facility']} -> "
            f"{recommendation['destination_facility']} | "
            f"{recommendation['destination_stockout_risk']} | "
            f"potential transfer: "
            f"{recommendation['potential_transfer_days']} days"
        )

    print("\nGovernance:")
    print(
        decision_summary["governance"]["note"]
    )


if __name__ == "__main__":
    main()