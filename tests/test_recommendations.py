import pandas as pd
import pytest

from src.recommendations import find_redistribution_opportunities


def _row(
    facility: str,
    medicine: str = "TestMed",
    days_of_stock: float = 50,
    lead_time_days: float = 14,
    expiry_days: float = 100,
    stockout_risk: str = "LOW",
) -> dict:
    return {
        "facility": facility,
        "medicine": medicine,
        "days_of_stock": days_of_stock,
        "lead_time_days": lead_time_days,
        "expiry_days": expiry_days,
        "stockout_risk": stockout_risk,
    }


def test_redistribution_protects_source_reserve():
    data = pd.DataFrame(
        [
            _row("Source", days_of_stock=50),
            _row(
                "Destination",
                days_of_stock=10,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert len(result) == 1
    assert result.iloc[0]["source_surplus_days"] == pytest.approx(22.0)
    assert result.iloc[0]["potential_transfer_days"] == pytest.approx(18.0)


def test_redistribution_only_matches_same_medicine():
    data = pd.DataFrame(
        [
            _row("Source", medicine="MedicineA", days_of_stock=100),
            _row(
                "Destination",
                medicine="MedicineB",
                days_of_stock=5,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert result.empty


def test_redistribution_requires_human_review():
    data = pd.DataFrame(
        [
            _row("Source", days_of_stock=100),
            _row(
                "Destination",
                days_of_stock=5,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert bool(result.iloc[0]["requires_human_review"]) is True


def test_destination_gap_is_not_over_allocated():
    data = pd.DataFrame(
        [
            _row("Source A", days_of_stock=100),
            _row("Source B", days_of_stock=100),
            _row(
                "Destination",
                days_of_stock=10,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert len(result) == 1
    assert result["potential_transfer_days"].sum() == pytest.approx(18.0)
    assert result.iloc[0]["destination_remaining_gap_days"] == pytest.approx(
        0.0
    )


def test_source_surplus_is_not_over_allocated():
    data = [
        _row("Source", days_of_stock=100),
        *[
            _row(
                f"Destination {index}",
                days_of_stock=10,
                stockout_risk="CRITICAL",
            )
            for index in range(6)
        ],
    ]

    result = find_redistribution_opportunities(pd.DataFrame(data))

    assert result["potential_transfer_days"].sum() == pytest.approx(72.0)
    assert (result["source_remaining_surplus_days"] >= 0).all()
    assert result["source_remaining_surplus_days"].min() == pytest.approx(0.0)


def test_critical_destinations_are_prioritized():
    data = pd.DataFrame(
        [
            _row("Source", days_of_stock=46),
            _row(
                "Critical",
                days_of_stock=10,
                stockout_risk="CRITICAL",
            ),
            _row(
                "High",
                days_of_stock=10,
                stockout_risk="HIGH",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert result.iloc[0]["destination_facility"] == "Critical"


def test_transfer_is_capped_by_source_expiry():
    data = pd.DataFrame(
        [
            _row("Source", days_of_stock=100, expiry_days=10),
            _row(
                "Destination",
                days_of_stock=5,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert len(result) == 1
    assert result.iloc[0]["potential_transfer_days"] == pytest.approx(10.0)
    assert result.iloc[0]["destination_remaining_gap_days"] == pytest.approx(
        13.0
    )


def test_nearly_expired_stock_is_not_recommended():
    data = pd.DataFrame(
        [
            _row("Source", days_of_stock=100, expiry_days=0.5),
            _row(
                "Destination",
                days_of_stock=5,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert result.empty


def test_negligible_transfer_is_skipped():
    data = pd.DataFrame(
        [
            _row("Source", days_of_stock=28.5),
            _row(
                "Destination",
                days_of_stock=10,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    assert result.empty


def test_recommendation_score_is_bounded():
    data = pd.DataFrame(
        [
            _row("Source", days_of_stock=100),
            _row(
                "Destination",
                days_of_stock=5,
                stockout_risk="CRITICAL",
            ),
        ]
    )

    result = find_redistribution_opportunities(data)

    score = result.iloc[0]["recommendation_score"]
    assert 0.0 <= score <= 1.0


def test_missing_required_columns():
    with pytest.raises(ValueError):
        find_redistribution_opportunities(
            pd.DataFrame([{"facility": "A", "medicine": "M"}])
        )


def test_unknown_risk_is_rejected():
    data = pd.DataFrame(
        [
            _row("Source"),
            _row("Destination", stockout_risk="UNKNOWN"),
        ]
    )

    with pytest.raises(ValueError):
        find_redistribution_opportunities(data)


def test_duplicate_facility_medicine_is_rejected():
    data = pd.DataFrame(
        [
            _row("Source"),
            _row("Source"),
        ]
    )

    with pytest.raises(ValueError):
        find_redistribution_opportunities(data)
