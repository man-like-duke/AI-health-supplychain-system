import pandas as pd

from src.config import TOP_RECOMMENDATIONS
from src.decisions import build_decision_summary


def _inventory_row(
    facility: str,
    medicine: str,
    days_of_stock: float,
    lead_time_days: float,
    expiry_days: float,
    stockout_risk: str,
    expiry_risk: str,
) -> dict:
    return {
        "facility": facility,
        "medicine": medicine,
        "days_of_stock": days_of_stock,
        "lead_time_days": lead_time_days,
        "expiry_days": expiry_days,
        "stockout_risk": stockout_risk,
        "expiry_risk": expiry_risk,
    }


def _recommendation_row(index: int, **overrides) -> dict:
    row = {
        "medicine": "TestMed",
        "source_facility": f"Source {index}",
        "destination_facility": "Facility A",
        "destination_stockout_risk": "CRITICAL",
        "destination_days_of_stock": 10,
        "destination_gap_days": 18,
        "potential_transfer_days": 18,
        "source_surplus_days": 50,
        "source_expiry_days": 100,
        "requires_human_review": True,
        "destination_remaining_gap_days": 0,
        "source_remaining_surplus_days": 32,
        "recommendation_score": 0.75,
    }
    row.update(overrides)
    return row


def test_decision_summary_counts_risks():
    inventory = pd.DataFrame(
        [
            _inventory_row(
                "Facility A",
                "Medicine A",
                10,
                14,
                100,
                "CRITICAL",
                "LOW",
            ),
            _inventory_row(
                "Facility B",
                "Medicine B",
                20,
                14,
                15,
                "LOW",
                "HIGH",
            ),
        ]
    )

    summary = build_decision_summary(inventory, pd.DataFrame())

    assert summary["summary"]["facilities_analyzed"] == 2
    assert summary["summary"]["critical_stockout_items"] == 1
    assert summary["summary"]["high_stockout_items"] == 0
    assert summary["summary"]["expiry_risk_items"] == 1


def test_decision_summary_requires_human_review():
    inventory = pd.DataFrame(
        [
            _inventory_row(
                "Source",
                "TestMed",
                100,
                14,
                100,
                "LOW",
                "LOW",
            )
        ]
    )

    recommendations = pd.DataFrame([_recommendation_row(0)])

    summary = build_decision_summary(inventory, recommendations)

    assert summary["governance"]["human_review_required"] is True
    assert summary["governance"]["autonomous_action"] is False
    assert summary["governance"]["data_type"] == "synthetic"


def test_decision_summary_limits_top_recommendations():
    inventory = pd.DataFrame(
        [
            _inventory_row(
                "Facility A",
                "TestMed",
                10,
                14,
                100,
                "CRITICAL",
                "LOW",
            )
        ]
    )

    recommendations = pd.DataFrame(
        [_recommendation_row(index) for index in range(10)]
    )

    summary = build_decision_summary(inventory, recommendations)

    assert (
        len(summary["redistribution_recommendations"]) == TOP_RECOMMENDATIONS
    )


def test_decision_summary_includes_allocation_fields():
    inventory = pd.DataFrame(
        [
            _inventory_row(
                "Facility A",
                "TestMed",
                10,
                14,
                100,
                "CRITICAL",
                "LOW",
            )
        ]
    )

    recommendations = pd.DataFrame([_recommendation_row(0)])
    summary = build_decision_summary(inventory, recommendations)

    recommendation = summary["redistribution_recommendations"][0]

    assert recommendation["destination_remaining_gap_days"] == 0
    assert recommendation["source_remaining_surplus_days"] == 32
    assert recommendation["recommendation_score"] == 0.75


def test_decision_summary_includes_assumptions():
    inventory = pd.DataFrame(
        [
            _inventory_row(
                "Facility A",
                "TestMed",
                10,
                14,
                100,
                "CRITICAL",
                "LOW",
            )
        ]
    )

    summary = build_decision_summary(inventory, pd.DataFrame())

    assumptions = summary["governance"]["assumptions"]
    assert assumptions
    assert any("30-day month" in assumption for assumption in assumptions)


def test_decision_summary_serializes_native_types():
    inventory = pd.DataFrame(
        [
            _inventory_row(
                "Facility A",
                "TestMed",
                10,
                14,
                100,
                "CRITICAL",
                "LOW",
            )
        ]
    )

    summary = build_decision_summary(inventory, pd.DataFrame())

    item = summary["critical_items"][0]
    assert type(item["days_of_stock"]) in (int, float)
    assert type(item["lead_time_days"]) in (int, float)
