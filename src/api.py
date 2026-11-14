from fastapi import FastAPI

from src.data import load_facility_data
from src.risk import analyze_inventory
from src.recommendations import find_redistribution_opportunities
from src.decisions import build_decision_summary
from src.llm import (
    GeminiProvider,
    build_explanation_request,
)


app = FastAPI(
    title="AI Health Supply Chain Decision Support API",
    description=(
        "Decision-support API for synthetic health supply-chain "
        "inventory risk and redistribution analysis."
    ),
    version="0.1.0",
)


def run_analysis():
    """Run the deterministic supply-chain analysis pipeline."""
    data = load_facility_data()
    inventory = analyze_inventory(data)
    recommendations = find_redistribution_opportunities(inventory)
    summary = build_decision_summary(
        inventory,
        recommendations,
    )

    return inventory, recommendations, summary


@app.get("/health")
def health_check():
    return {
        "status": "healthy",
        "service": "ai-health-supply-chain",
        "version": "0.1.0",
    }


@app.get("/inventory")
def get_inventory():
    inventory, _, _ = run_analysis()

    return inventory.to_dict(orient="records")


@app.get("/recommendations")
def get_recommendations():
    _, recommendations, _ = run_analysis()

    return recommendations.to_dict(orient="records")


@app.get("/summary")
def get_summary():
    _, _, summary = run_analysis()

    return summary

@app.get("/explanation")
def get_explanation():
    """Generate a human-readable explanation of the current analysis."""

    _, _, summary = run_analysis()

    request = build_explanation_request(summary)
    provider = GeminiProvider()

    explanation = provider.generate_explanation(
        request["prompt"]
    )

    return {
        "explanation": explanation,
        "governance": {
            "data_type": request["data_type"],
            "autonomous_action": request["autonomous_action"],
            "human_review_required": request[
                "human_review_required"
            ],
        },
    }