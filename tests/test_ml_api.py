"""API tests for the stockout prediction endpoint."""

import sys
from datetime import date
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from src.api import app, get_stockout_predictor
from src.errors import DataValidationError, ModelNotAvailableError

client = TestClient(app)

BASE_PAYLOAD = {
    "facility": "Kaduna North",
    "region": "Kaduna",
    "medicine": "Amoxicillin",
    "current_stock": 180,
    "monthly_consumption": 450,
    "lead_time_days": 21,
    "expiry_days": 120,
    "recent_consumption_trend": 1.1,
    "historical_stockout_count": 2,
    "replenishment_frequency": 1.4,
    "month": 7,
}


@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    yield
    app.dependency_overrides.clear()


class FakePredictor:
    def __init__(self, predicted_class=1, probability=0.77):
        self.predicted_class = predicted_class
        self.probability = probability
        self.limitations = ["Synthetic data only.", "Human review required."]
        self.last_features = None

    def predict(self, features):
        self.last_features = features
        return SimpleNamespace(
            predicted_class=self.predicted_class,
            prediction_label=(
                "stockout_likely"
                if self.predicted_class == 1
                else "no_stockout_expected"
            ),
            probability=self.probability,
            probability_band=(
                "HIGH"
                if self.probability >= 0.7
                else "MODERATE"
                if self.probability >= 0.4
                else "LOW"
            ),
            threshold=0.2,
            model_id="stockout-risk-30d",
            model_version="1.0.0",
        )


def _use(fake):
    app.dependency_overrides[get_stockout_predictor] = lambda: fake


def test_predict_stockout_returns_prediction_and_reference():
    fake = FakePredictor()
    _use(fake)

    response = client.post("/predict-stockout", json=BASE_PAYLOAD)

    assert response.status_code == 200

    data = response.json()

    assert data["facility"] == "Kaduna North"
    assert data["medicine"] == "Amoxicillin"
    assert data["predicted_class"] == 1
    assert data["prediction_label"] == "stockout_likely"
    assert data["probability"] == pytest.approx(0.77)
    assert data["probability_band"] == "HIGH"
    assert data["threshold"] == pytest.approx(0.2)
    assert data["model_id"] == "stockout-risk-30d"
    assert data["model_version"] == "1.0.0"
    assert data["deterministic_reference"]["stockout_risk"]
    assert data["deterministic_reference"]["days_of_stock"] > 0
    assert data["governance"]["autonomous_action"] is False
    assert data["governance"]["human_review_required"] is True
    assert data["governance"]["data_type"] == "synthetic"
    assert data["governance"]["limitations"] == fake.limitations
    assert "predictive evidence" in data["governance"]["note"]


def test_predict_stockout_defaults_month_to_today():
    fake = FakePredictor(predicted_class=0, probability=0.1)
    _use(fake)
    payload = dict(BASE_PAYLOAD)
    del payload["month"]

    response = client.post("/predict-stockout", json=payload)

    assert response.status_code == 200
    assert fake.last_features["month"] == date.today().month
    assert response.json()["prediction_label"] == "no_stockout_expected"
    assert response.json()["probability_band"] == "LOW"


def test_predict_stockout_returns_null_reference_for_unknown_pair():
    fake = FakePredictor()
    _use(fake)
    payload = dict(BASE_PAYLOAD)
    payload["facility"] = "Unknown Facility"

    response = client.post("/predict-stockout", json=payload)

    assert response.status_code == 200
    assert response.json()["deterministic_reference"] is None


def test_predict_stockout_survives_missing_deterministic_data(monkeypatch):
    fake = FakePredictor()
    _use(fake)

    def raise_validation_error():
        raise DataValidationError("invalid dataset")

    monkeypatch.setattr("src.api.run_analysis", raise_validation_error)

    response = client.post("/predict-stockout", json=BASE_PAYLOAD)

    assert response.status_code == 200
    assert response.json()["deterministic_reference"] is None


@pytest.mark.parametrize(
    "overrides",
    [
        {"current_stock": -1},
        {"monthly_consumption": 0},
        {"lead_time_days": 0},
        {"expiry_days": -5},
        {"recent_consumption_trend": 0},
        {"replenishment_frequency": -1},
        {"historical_stockout_count": -1},
        {"month": 13},
        {"month": 0},
        {"facility": ""},
        {"facility": "   "},
        {"medicine": ""},
        {"region": ""},
    ],
)
def test_predict_stockout_rejects_invalid_values(overrides):
    fake = FakePredictor()
    _use(fake)
    payload = {**BASE_PAYLOAD, **overrides}

    response = client.post("/predict-stockout", json=payload)

    assert response.status_code == 422
    assert fake.last_features is None


def test_predict_stockout_requires_all_fields():
    payload = dict(BASE_PAYLOAD)
    del payload["monthly_consumption"]

    response = client.post("/predict-stockout", json=payload)

    assert response.status_code == 422


def test_predict_stockout_rejects_extra_fields():
    payload = {**BASE_PAYLOAD, "unexpected": 1}

    response = client.post("/predict-stockout", json=payload)

    assert response.status_code == 422


def test_predict_stockout_requires_text_fields():
    payload = dict(BASE_PAYLOAD)
    del payload["facility"]

    response = client.post("/predict-stockout", json=payload)

    assert response.status_code == 422


def test_missing_model_maps_to_503():
    def raise_missing_model():
        raise ModelNotAvailableError("model artifact is missing")

    app.dependency_overrides[get_stockout_predictor] = raise_missing_model

    response = client.post("/predict-stockout", json=BASE_PAYLOAD)

    assert response.status_code == 503
    assert response.json()["detail"] == "model artifact is missing"


def test_dependency_reports_missing_ml_dependencies(monkeypatch):
    monkeypatch.setitem(sys.modules, "ml.predict", None)

    with pytest.raises(ModelNotAvailableError, match="not installed"):
        get_stockout_predictor()


def test_root_endpoint_advertises_prediction_route():
    response = client.get("/")

    assert response.status_code == 200
    assert response.json()["predict_stockout"] == "/predict-stockout"


def test_dashboard_includes_ml_prediction_panel():
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert 'id="ml-heading"' in response.text
    assert "ML prediction" in response.text
    assert "Decision-support recommendation" in response.text

    script = client.get("/static/app.js")
    assert script.status_code == 200
    assert "predictStockout" in script.text
    assert "renderPrediction" in script.text


def test_prediction_endpoint_works_with_real_artifact():
    response = client.post("/predict-stockout", json=BASE_PAYLOAD)

    assert response.status_code == 200

    data = response.json()

    assert data["model_id"] == "stockout-risk-30d"
    assert 0.0 <= data["probability"] <= 1.0
    assert data["predicted_class"] in {0, 1}
    assert data["probability_band"] in {"LOW", "MODERATE", "HIGH"}
    assert data["governance"]["autonomous_action"] is False
