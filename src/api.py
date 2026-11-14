import logging
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from src import __version__
from src.errors import (
    DataValidationError,
    LLMConfigurationError,
    LLMError,
)
from src.llm import (
    LLMProvider,
    build_explanation_request,
    get_gemini_provider,
    validate_explanation,
)
from src.pipeline import run_analysis
from src.serialization import dataframe_to_records

logger = logging.getLogger(__name__)

STATIC_DIR = Path(__file__).resolve().parent.parent / "static"

app = FastAPI(
    title="AI Health Supply Chain Decision Support API",
    description=(
        "Decision-support API for synthetic health supply-chain "
        "inventory risk and redistribution analysis."
    ),
    version=__version__,
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class HealthResponse(BaseModel):
    status: str
    service: str
    version: str


class InventoryItem(BaseModel):
    facility: str
    region: str
    medicine: str
    current_stock: float
    monthly_consumption: float
    lead_time_days: float
    expiry_days: float
    days_of_stock: float
    target_days: float
    stockout_risk: str
    expiry_risk: str


class Recommendation(BaseModel):
    medicine: str
    source_facility: str
    destination_facility: str
    source_days_of_stock: float
    source_reserve_days: float
    source_surplus_days: float
    source_remaining_surplus_days: float
    destination_days_of_stock: float
    destination_target_days: float
    destination_gap_days: float
    destination_remaining_gap_days: float
    potential_transfer_days: float
    source_expiry_days: float
    destination_stockout_risk: str
    risk_priority: int
    recommendation_score: float
    requires_human_review: bool


class SummaryCounts(BaseModel):
    facilities_analyzed: int
    medicine_facility_records: int
    critical_stockout_items: int
    high_stockout_items: int
    expiry_risk_items: int
    redistribution_candidates: int


class CriticalItem(BaseModel):
    facility: str
    medicine: str
    days_of_stock: float
    lead_time_days: float
    expiry_days: float
    stockout_risk: str
    expiry_risk: str


class RecommendationSummary(BaseModel):
    medicine: str
    source_facility: str
    destination_facility: str
    destination_stockout_risk: str
    destination_days_of_stock: float
    destination_gap_days: float
    potential_transfer_days: float
    source_surplus_days: float
    source_expiry_days: float
    requires_human_review: bool
    destination_remaining_gap_days: float | None = None
    source_remaining_surplus_days: float | None = None
    recommendation_score: float | None = None


class Governance(BaseModel):
    data_type: str
    autonomous_action: bool
    human_review_required: bool
    note: str
    assumptions: list[str] = Field(default_factory=list)


class SummaryResponse(BaseModel):
    summary: SummaryCounts
    critical_items: list[CriticalItem]
    redistribution_recommendations: list[RecommendationSummary]
    governance: Governance


class ExplanationGovernance(BaseModel):
    data_type: str
    autonomous_action: bool
    human_review_required: bool
    guardrail_warnings: list[str] = Field(default_factory=list)


class ExplanationResponse(BaseModel):
    explanation: str
    governance: ExplanationGovernance


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency so tests can override the provider."""
    return get_gemini_provider()


@app.exception_handler(DataValidationError)
async def handle_data_validation_error(request, exc):
    return JSONResponse(
        status_code=422,
        content={"detail": str(exc)},
    )


@app.exception_handler(LLMConfigurationError)
async def handle_llm_configuration_error(request, exc):
    return JSONResponse(
        status_code=503,
        content={
            "detail": (
                "Explanation service is not configured. Set GEMINI_API_KEY."
            )
        },
    )


@app.exception_handler(LLMError)
async def handle_llm_error(request, exc):
    logger.warning("Explanation request failed: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": "Explanation service is temporarily unavailable."},
    )


@app.exception_handler(Exception)
async def handle_unexpected_error(request, exc):
    logger.exception("Unhandled error on %s", request.url.path)
    return JSONResponse(
        status_code=500,
        content={"detail": "Internal server error."},
    )


@app.get("/", include_in_schema=False)
def root():
    return {
        "service": "ai-health-supply-chain",
        "version": __version__,
        "dashboard": "/dashboard",
        "docs": "/docs",
        "health": "/health",
    }


@app.get("/dashboard", include_in_schema=False)
def dashboard():
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/health", response_model=HealthResponse)
def health_check():
    return {
        "status": "healthy",
        "service": "ai-health-supply-chain",
        "version": __version__,
    }


@app.get("/inventory", response_model=list[InventoryItem])
def get_inventory(
    region: str | None = Query(
        default=None,
        description="Filter by region (case-insensitive).",
    ),
    medicine: str | None = Query(
        default=None,
        description="Filter by medicine (case-insensitive).",
    ),
    stockout_risk: str | None = Query(
        default=None,
        description="Filter by stockout risk classification.",
    ),
):
    inventory, _, _ = run_analysis()

    if region:
        inventory = inventory[
            inventory["region"].str.casefold() == region.casefold()
        ]

    if medicine:
        inventory = inventory[
            inventory["medicine"].str.casefold() == medicine.casefold()
        ]

    if stockout_risk:
        inventory = inventory[
            inventory["stockout_risk"].str.casefold()
            == stockout_risk.casefold()
        ]

    return dataframe_to_records(inventory)


@app.get("/recommendations", response_model=list[Recommendation])
def get_recommendations(
    medicine: str | None = Query(
        default=None,
        description="Filter by medicine (case-insensitive).",
    ),
    source_facility: str | None = Query(
        default=None,
        description="Filter by source facility (case-insensitive).",
    ),
    destination_facility: str | None = Query(
        default=None,
        description="Filter by destination facility (case-insensitive).",
    ),
):
    _, recommendations, _ = run_analysis()

    if recommendations.empty:
        return []

    if medicine:
        recommendations = recommendations[
            recommendations["medicine"].str.casefold() == medicine.casefold()
        ]

    if source_facility:
        recommendations = recommendations[
            recommendations["source_facility"].str.casefold()
            == source_facility.casefold()
        ]

    if destination_facility:
        recommendations = recommendations[
            recommendations["destination_facility"].str.casefold()
            == destination_facility.casefold()
        ]

    return dataframe_to_records(recommendations)


@app.get("/summary", response_model=SummaryResponse)
def get_summary():
    _, _, summary = run_analysis()

    return summary


@app.get("/explanation", response_model=ExplanationResponse)
def get_explanation(
    refresh: bool = False,
    provider: LLMProvider = Depends(get_llm_provider),
):
    """Generate a human-readable explanation of the current analysis.

    Pass ``?refresh=true`` to bypass the provider's in-process cache.
    """
    _, _, summary = run_analysis()

    request = build_explanation_request(summary)
    explanation = provider.generate_explanation(
        request["prompt"],
        refresh=refresh,
    )

    return {
        "explanation": explanation,
        "governance": {
            "data_type": request["data_type"],
            "autonomous_action": request["autonomous_action"],
            "human_review_required": request["human_review_required"],
            "guardrail_warnings": validate_explanation(explanation),
        },
    }
