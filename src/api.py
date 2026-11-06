from fastapi import FastAPI

from src.data import load_facility_data
from src.risk import analyze_inventory
from src.recommendations import find_redistribution_opportunities
from src.decisions import build_decision_summary


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