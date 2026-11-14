import pytest

from src.risk import (
    calculate_days_of_stock,
    classify_expiry_risk,
    classify_stockout_risk,
)


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


def test_medium_stockout_risk():
    risk = classify_stockout_risk(
        days_of_stock=25,
        lead_time_days=14,
    )
    assert risk == "MEDIUM"


def test_low_stockout_risk():
    risk = classify_stockout_risk(
        days_of_stock=30,
        lead_time_days=14,
    )
    assert risk == "LOW"


def test_invalid_consumption():
    with pytest.raises(ValueError):
        calculate_days_of_stock(
            current_stock=100,
            monthly_consumption=0,
        )


def test_negative_lead_time():
    with pytest.raises(ValueError):
        classify_stockout_risk(
            days_of_stock=10,
            lead_time_days=-1,
        )


def test_high_expiry_risk():
    risk = classify_expiry_risk(
        days_of_stock=90,
        expiry_days=45,
    )
    assert risk == "HIGH"


def test_medium_expiry_risk_when_buffer_is_thin():
    risk = classify_expiry_risk(
        days_of_stock=90,
        expiry_days=100,
    )
    assert risk == "MEDIUM"


def test_medium_expiry_risk_at_exact_coverage():
    risk = classify_expiry_risk(
        days_of_stock=90,
        expiry_days=90,
    )
    assert risk == "MEDIUM"


def test_low_expiry_risk_when_buffer_is_comfortable():
    risk = classify_expiry_risk(
        days_of_stock=90,
        expiry_days=120,
    )
    assert risk == "LOW"


def test_zero_stock_has_no_expiry_risk():
    risk = classify_expiry_risk(
        days_of_stock=0,
        expiry_days=10,
    )
    assert risk == "LOW"


def test_negative_expiry_days():
    with pytest.raises(ValueError):
        classify_expiry_risk(
            days_of_stock=10,
            expiry_days=-1,
        )
