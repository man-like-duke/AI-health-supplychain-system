import pytest

from src import pipeline
from src.errors import DataValidationError


@pytest.fixture(autouse=True)
def clear_cache():
    pipeline.clear_analysis_cache()
    yield
    pipeline.clear_analysis_cache()


def test_run_analysis_returns_consistent_results():
    first_inventory, first_recommendations, first_summary = (
        pipeline.run_analysis()
    )
    second_inventory, second_recommendations, second_summary = (
        pipeline.run_analysis()
    )

    assert first_inventory.equals(second_inventory)
    assert first_recommendations.equals(second_recommendations)
    assert first_summary == second_summary


def test_run_analysis_reuses_cached_pipeline(monkeypatch):
    calls = {"count": 0}
    original_loader = pipeline.load_facility_data

    def counting_loader(path):
        calls["count"] += 1
        return original_loader(path)

    monkeypatch.setattr(pipeline, "load_facility_data", counting_loader)

    pipeline.run_analysis()
    pipeline.run_analysis()

    assert calls["count"] == 1


def test_run_analysis_returns_copies():
    inventory, recommendations, summary = pipeline.run_analysis()
    inventory.loc[0, "facility"] = "mutated"
    recommendations.loc[0, "source_facility"] = "mutated"
    summary["summary"]["facilities_analyzed"] = -1

    fresh_inventory, fresh_recommendations, fresh_summary = (
        pipeline.run_analysis()
    )

    assert fresh_inventory.loc[0, "facility"] != "mutated"
    assert fresh_recommendations.loc[0, "source_facility"] != "mutated"
    assert fresh_summary["summary"]["facilities_analyzed"] != -1


def test_run_analysis_missing_file(tmp_path):
    with pytest.raises(DataValidationError, match="not found"):
        pipeline.run_analysis(tmp_path / "missing.csv")
