import pytest
from fastapi.testclient import TestClient

from src import __version__
from src.api import app, get_llm_provider
from src.errors import (
    DataValidationError,
    LLMConfigurationError,
    LLMServiceError,
)

client = TestClient(app)


@pytest.fixture(autouse=True)
def reset_dependency_overrides():
    yield
    app.dependency_overrides.clear()


class FakeProvider:
    def __init__(self, text=None, error=None):
        self.text = text or (
            "CRITICAL and HIGH stockout items are reported separately. "
            "Human review is required before any action."
        )
        self.error = error
        self.calls = 0
        self.last_refresh = None

    def generate_explanation(self, prompt, refresh=False):
        self.calls += 1
        self.last_refresh = refresh
        if self.error is not None:
            raise self.error
        return self.text


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "healthy"
    assert data["service"] == "ai-health-supply-chain"
    assert data["version"] == __version__


def test_root_endpoint():
    response = client.get("/")

    assert response.status_code == 200

    data = response.json()

    assert data["version"] == __version__
    assert data["dashboard"] == "/dashboard"


def test_dashboard_serves_html():
    response = client.get("/dashboard")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")

    body = response.text
    assert "<title>Supply Chain Decision Support</title>" in body
    assert 'src="/static/app.js"' in body
    assert 'href="/static/styles.css"' in body


def test_static_stylesheet_is_served():
    response = client.get("/static/styles.css")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "--critical" in response.text


def test_static_javascript_is_served():
    response = client.get("/static/app.js")

    assert response.status_code == 200
    assert "javascript" in response.headers["content-type"]
    assert "/explanation" in response.text
    assert "renderExplanation" in response.text


def test_inventory_endpoint():
    response = client.get("/inventory")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 52

    assert "facility" in data[0]
    assert "medicine" in data[0]
    assert "days_of_stock" in data[0]
    assert "target_days" in data[0]
    assert "stockout_risk" in data[0]
    assert "expiry_risk" in data[0]


def test_recommendations_endpoint_respects_allocation_limits():
    response = client.get("/recommendations")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert data

    for recommendation in data:
        assert "source_facility" in recommendation
        assert "destination_facility" in recommendation
        assert recommendation["requires_human_review"] is True
        assert recommendation["potential_transfer_days"] > 0
        assert (
            recommendation["potential_transfer_days"]
            <= recommendation["destination_gap_days"] + 1e-9
        )
        assert recommendation["destination_remaining_gap_days"] >= 0
        assert recommendation["source_remaining_surplus_days"] >= 0
        assert 0.0 <= recommendation["recommendation_score"] <= 1.0

    destination_totals = {}
    source_totals = {}
    source_initial_surplus = {}

    for recommendation in data:
        destination_key = (
            recommendation["medicine"],
            recommendation["destination_facility"],
        )
        destination_totals.setdefault(destination_key, 0.0)
        destination_totals[destination_key] += recommendation[
            "potential_transfer_days"
        ]

        source_key = (
            recommendation["medicine"],
            recommendation["source_facility"],
        )
        source_totals.setdefault(source_key, 0.0)
        source_totals[source_key] += recommendation["potential_transfer_days"]
        source_initial_surplus[source_key] = max(
            source_initial_surplus.get(source_key, 0.0),
            recommendation["source_surplus_days"],
        )

    gaps = {
        (
            recommendation["medicine"],
            recommendation["destination_facility"],
        ): recommendation["destination_gap_days"]
        for recommendation in data
    }

    for key, total in destination_totals.items():
        assert total <= gaps[key] + 1e-9

    for key, total in source_totals.items():
        assert total <= source_initial_surplus[key] + 1e-9


def test_inventory_region_filter_is_case_insensitive():
    response = client.get("/inventory", params={"region": "lagos"})

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 7
    assert {item["region"] for item in data} == {"Lagos"}


def test_inventory_stockout_risk_filter():
    response = client.get(
        "/inventory",
        params={"stockout_risk": "critical"},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 3
    assert all(item["stockout_risk"] == "CRITICAL" for item in data)


def test_recommendations_medicine_filter():
    response = client.get(
        "/recommendations",
        params={"medicine": "ors"},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert data[0]["medicine"] == "ORS"


def test_recommendations_destination_filter():
    response = client.get(
        "/recommendations",
        params={"destination_facility": "kaduna north"},
    )

    assert response.status_code == 200

    data = response.json()

    assert len(data) == 1
    assert all(item["destination_facility"] == "Kaduna North" for item in data)


def test_summary_endpoint_is_consistent_with_other_endpoints():
    inventory = client.get("/inventory").json()
    recommendations = client.get("/recommendations").json()
    response = client.get("/summary")

    assert response.status_code == 200

    data = response.json()
    summary = data["summary"]

    assert summary["medicine_facility_records"] == len(inventory)
    assert summary["facilities_analyzed"] == len(
        {item["facility"] for item in inventory}
    )
    assert summary["critical_stockout_items"] == sum(
        item["stockout_risk"] == "CRITICAL" for item in inventory
    )
    assert summary["high_stockout_items"] == sum(
        item["stockout_risk"] == "HIGH" for item in inventory
    )
    assert summary["expiry_risk_items"] == sum(
        item["expiry_risk"] in {"HIGH", "MEDIUM"} for item in inventory
    )
    assert summary["redistribution_candidates"] == len(recommendations)

    assert data["governance"]["autonomous_action"] is False
    assert data["governance"]["human_review_required"] is True
    assert data["governance"]["data_type"] == "synthetic"
    assert data["governance"]["assumptions"]


def test_explanation_endpoint_with_provider_override():
    provider = FakeProvider()
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.get("/explanation")

    assert response.status_code == 200

    data = response.json()
    assert data["explanation"]
    assert data["governance"]["guardrail_warnings"] == []
    assert data["governance"]["human_review_required"] is True
    assert provider.calls == 1


def test_explanation_endpoint_reports_guardrail_warnings():
    provider = FakeProvider(text="The analysis is complete.")
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.get("/explanation")

    assert response.status_code == 200

    warnings = response.json()["governance"]["guardrail_warnings"]
    assert len(warnings) == 3


def test_explanation_refresh_parameter_is_forwarded():
    provider = FakeProvider()
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.get("/explanation?refresh=true")

    assert response.status_code == 200
    assert provider.last_refresh is True


def test_data_validation_errors_map_to_422(monkeypatch):
    def raise_validation_error():
        raise DataValidationError("invalid dataset")

    monkeypatch.setattr("src.api.run_analysis", raise_validation_error)

    response = client.get("/inventory")

    assert response.status_code == 422
    assert response.json()["detail"] == "invalid dataset"


def test_missing_llm_configuration_maps_to_503():
    def raise_configuration_error():
        raise LLMConfigurationError("missing key")

    app.dependency_overrides[get_llm_provider] = raise_configuration_error

    response = client.get("/explanation")

    assert response.status_code == 503
    assert "GEMINI_API_KEY" in response.json()["detail"]


def test_llm_service_errors_map_to_503():
    provider = FakeProvider(error=LLMServiceError("upstream failed"))
    app.dependency_overrides[get_llm_provider] = lambda: provider

    response = client.get("/explanation")

    assert response.status_code == 503
    assert "temporarily unavailable" in response.json()["detail"]
