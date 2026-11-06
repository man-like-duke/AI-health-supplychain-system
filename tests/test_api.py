from fastapi.testclient import TestClient

from src.api import app


client = TestClient(app)


def test_health_endpoint():
    response = client.get("/health")

    assert response.status_code == 200

    data = response.json()

    assert data["status"] == "healthy"
    assert data["service"] == "ai-health-supply-chain"
    assert data["version"] == "0.1.0"


def test_inventory_endpoint():
    response = client.get("/inventory")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 15

    assert "facility" in data[0]
    assert "medicine" in data[0]
    assert "days_of_stock" in data[0]
    assert "stockout_risk" in data[0]


def test_recommendations_endpoint():
    response = client.get("/recommendations")

    assert response.status_code == 200

    data = response.json()

    assert isinstance(data, list)
    assert len(data) == 12

    assert "source_facility" in data[0]
    assert "destination_facility" in data[0]
    assert "requires_human_review" in data[0]


def test_summary_endpoint():
    response = client.get("/summary")

    assert response.status_code == 200

    data = response.json()

    assert data["summary"]["facilities_analyzed"] == 5
    assert data["summary"]["critical_stockout_items"] == 2
    assert data["summary"]["high_stockout_items"] == 1
    assert data["summary"]["redistribution_candidates"] == 12

    assert data["governance"]["autonomous_action"] is False
    assert data["governance"]["human_review_required"] is True
    assert data["governance"]["data_type"] == "synthetic"