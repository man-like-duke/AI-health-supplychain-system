import pandas as pd
import pytest

from src.risk import (
    calculate_days_of_stock,
    classify_expiry_risk,
    classify_stockout_risk,
)
from src.recommendations import find_redistribution_opportunities
from src.decisions import build_decision_summary
from src.llm import build_explanation_request


def test_days_of_stock():
    days = calculate_days_of_stock(
        current_stock=100,
        monthly_consumption=250,
    )
    assert days == pytest.approx(12.0)


def test_critical_stockout_risk():
    risk = classify_stockout_risk(
        days_of_stock=12,
        lead_time_days=14,
    )
    assert risk == "CRITICAL"


def test_high_stockout_risk():
    risk = classify_stockout_risk(
        days_of_stock=18,
        lead_time_days=14,
    )
    assert risk == "HIGH"


def test_low_stockout_risk():
    risk = classify_stockout_risk(
        days_of_stock=30,
        lead_time_days=14,
    )
    assert risk == "LOW"


def test_high_expiry_risk():
    risk = classify_expiry_risk(
        days_of_stock=90,
        expiry_days=45,
    )
    assert risk == "HIGH"


def test_invalid_consumption():
    with pytest.raises(ValueError):
        calculate_days_of_stock(
            current_stock=100,
            monthly_consumption=0,
        )


def test_redistribution_protects_source_reserve():
    data = pd.DataFrame(
        [
            {
                "facility": "Source",
                "medicine": "TestMed",
                "days_of_stock": 50,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "LOW",
            },
            {
                "facility": "Destination",
                "medicine": "TestMed",
                "days_of_stock": 10,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "CRITICAL",
            },
        ]
    )

    result = find_redistribution_opportunities(data)

    assert len(result) == 1
    assert result.iloc[0]["source_surplus_days"] == pytest.approx(22.0)
    assert result.iloc[0]["potential_transfer_days"] == pytest.approx(18.0)


def test_redistribution_only_matches_same_medicine():
    data = pd.DataFrame(
        [
            {
                "facility": "Source",
                "medicine": "MedicineA",
                "days_of_stock": 100,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "LOW",
            },
            {
                "facility": "Destination",
                "medicine": "MedicineB",
                "days_of_stock": 5,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "CRITICAL",
            },
        ]
    )

    result = find_redistribution_opportunities(data)

    assert result.empty


def test_redistribution_requires_human_review():
    data = pd.DataFrame(
        [
            {
                "facility": "Source",
                "medicine": "TestMed",
                "days_of_stock": 100,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "LOW",
            },
            {
                "facility": "Destination",
                "medicine": "TestMed",
                "days_of_stock": 5,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "CRITICAL",
            },
        ]
    )
    

    result = find_redistribution_opportunities(data)

    assert bool(result.iloc[0]["requires_human_review"]) is True

def test_decision_summary_counts_risks():
    inventory = pd.DataFrame(
        [
            {
                "facility": "Facility A",
                "medicine": "Medicine A",
                "days_of_stock": 10,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "CRITICAL",
                "expiry_risk": "LOW",
            },
            {
                "facility": "Facility B",
                "medicine": "Medicine B",
                "days_of_stock": 20,
                "lead_time_days": 14,
                "expiry_days": 15,
                "stockout_risk": "LOW",
                "expiry_risk": "HIGH",
            },
        ]
    )

    recommendations = pd.DataFrame()

    summary = build_decision_summary(
        inventory,
        recommendations,
    )

    assert summary["summary"]["facilities_analyzed"] == 2
    assert summary["summary"]["critical_stockout_items"] == 1
    assert summary["summary"]["high_stockout_items"] == 0
    assert summary["summary"]["expiry_risk_items"] == 1


def test_decision_summary_requires_human_review():
    inventory = pd.DataFrame(
        [
            {
                "facility": "Source",
                "medicine": "TestMed",
                "days_of_stock": 100,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "LOW",
                "expiry_risk": "LOW",
            }
        ]
    )

    recommendations = pd.DataFrame(
        [
            {
                "medicine": "TestMed",
                "source_facility": "Source",
                "destination_facility": "Destination",
                "destination_stockout_risk": "CRITICAL",
                "destination_days_of_stock": 5,
                "destination_gap_days": 23,
                "potential_transfer_days": 20,
                "source_surplus_days": 50,
                "source_expiry_days": 100,
                "requires_human_review": True,
            }
        ]
    )

    summary = build_decision_summary(
        inventory,
        recommendations,
    )

    assert summary["governance"]["human_review_required"] is True
    assert summary["governance"]["autonomous_action"] is False


def test_decision_summary_limits_top_recommendations():
    inventory = pd.DataFrame(
        [
            {
                "facility": "Facility A",
                "medicine": "TestMed",
                "days_of_stock": 10,
                "lead_time_days": 14,
                "expiry_days": 100,
                "stockout_risk": "CRITICAL",
                "expiry_risk": "LOW",
            }
        ]
    )

    recommendations = pd.DataFrame(
        [
            {
                "medicine": "TestMed",
                "source_facility": f"Source {i}",
                "destination_facility": "Facility A",
                "destination_stockout_risk": "CRITICAL",
                "destination_days_of_stock": 10,
                "destination_gap_days": 18,
                "potential_transfer_days": 18,
                "source_surplus_days": 50,
                "source_expiry_days": 100,
                "requires_human_review": True,
            }
            for i in range(10)
        ]
    )

    summary = build_decision_summary(
        inventory,
        recommendations,
    )

    assert len(summary["redistribution_recommendations"]) == 5

def test_explanation_request_preserves_governance_controls():
    decision_summary = {
        "governance": {
            "data_type": "synthetic",
            "autonomous_action": False,
            "human_review_required": True,
        }
    }

    request = build_explanation_request(decision_summary)

    assert request["data_type"] == "synthetic"
    assert request["autonomous_action"] is False
    assert request["human_review_required"] is True
    assert request["system_role"] == (
        "health-supply-chain-explanation-assistant"
    )

    assert "Do not recalculate or change any risk classification." in (
        request["prompt"]
    )

    assert "Do not make autonomous operational decisions." in (
        request["prompt"]
    )