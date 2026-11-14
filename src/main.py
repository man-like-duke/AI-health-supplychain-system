import argparse
import json
from pathlib import Path

import pandas as pd

from src.pipeline import run_analysis


def _print_human_readable(
    inventory: pd.DataFrame,
    opportunities: pd.DataFrame,
    decision_summary: dict,
) -> None:
    print("\n=== INVENTORY RISK ANALYSIS ===\n")

    columns = [
        "facility",
        "medicine",
        "days_of_stock",
        "stockout_risk",
        "expiry_risk",
    ]

    print(inventory[columns].to_string(index=False))

    print("\n=== POTENTIAL REDISTRIBUTION OPPORTUNITIES ===\n")

    if opportunities.empty:
        print("No potential redistribution opportunities identified.")
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

        print(opportunities[display_columns].to_string(index=False))

    print("\n=== DECISION SUPPORT SUMMARY ===\n")

    summary = decision_summary["summary"]

    print(f"Facilities analyzed: {summary['facilities_analyzed']}")
    print(f"Critical stockout items: {summary['critical_stockout_items']}")
    print(f"High stockout items: {summary['high_stockout_items']}")
    print(f"Expiry-risk items: {summary['expiry_risk_items']}")
    print(f"Redistribution candidates: {summary['redistribution_candidates']}")

    print("\nTop recommendations:")

    for recommendation in decision_summary["redistribution_recommendations"]:
        print(
            f"- {recommendation['medicine']}: "
            f"{recommendation['source_facility']} -> "
            f"{recommendation['destination_facility']} | "
            f"{recommendation['destination_stockout_risk']} | "
            f"potential transfer: "
            f"{recommendation['potential_transfer_days']} days"
        )

    print("\nAssumptions:")
    for assumption in decision_summary["governance"]["assumptions"]:
        print(f"- {assumption}")

    print("\nGovernance:")
    print(decision_summary["governance"]["note"])


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run the health supply-chain decision-support analysis.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=None,
        help="Path to a facility CSV file (defaults to data/facilities.csv).",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the decision summary as JSON.",
    )
    args = parser.parse_args(argv)

    inventory, opportunities, decision_summary = run_analysis(args.data)

    if args.json:
        print(json.dumps(decision_summary, indent=2))
        return 0

    _print_human_readable(inventory, opportunities, decision_summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
