import logging
from datetime import date
from pathlib import Path

from fastapi import Depends, FastAPI, Query
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, field_validator

from src import __version__
from src.errors import (
    DataValidationError,
    LLMConfigurationError,
    LLMError,
    ModelNotAvailableError,
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


class StockoutPredictionRequest(BaseModel):
    """Inputs available at prediction time for one facility/medicine pair."""

    model_config = ConfigDict(extra="forbid")

    facility: str = Field(min_length=1, max_length=120)
    region: str = Field(min_length=1, max_length=120)
    medicine: str = Field(min_length=1, max_length=120)
    current_stock: float = Field(ge=0)
    monthly_consumption: float = Field(gt=0)
    lead_time_days: float = Field(gt=0)
    expiry_days: float = Field(ge=0)
    recent_consumption_trend: float = Field(default=1.0, gt=0, le=5)
    historical_stockout_count: int = Field(default=0, ge=0, le=60)
    replenishment_frequency: float = Field(default=1.0, ge=0, le=30)
    month: int | None = Field(default=None, ge=1, le=12)

    @field_validator("facility", "region", "medicine")
    @classmethod
    def _strip_text(cls, value: str) -> str:
        stripped = value.strip()
        if not stripped:
            raise ValueError("must not be blank")
        return stripped


class DeterministicReference(BaseModel):
    stockout_risk: str
    days_of_stock: float
    lead_time_days: float


class PredictionGovernance(BaseModel):
    data_type: str
    autonomous_action: bool
    human_review_required: bool
    note: str
    limitations: list[str] = Field(default_factory=list)


class StockoutPredictionResponse(BaseModel):
    facility: str
    medicine: str
    predicted_class: int
    prediction_label: str
    probability: float
    probability_band: str
    threshold: float
    model_id: str
    model_version: str
    deterministic_reference: DeterministicReference | None = None
    governance: PredictionGovernance


def get_llm_provider() -> LLMProvider:
    """FastAPI dependency so tests can override the provider."""
    return get_gemini_provider()


def get_stockout_predictor():
    """FastAPI dependency so tests can override the ML model.

    The import is local so the deterministic endpoints keep working when
    the optional ML dependencies are not installed.
    """
    try:
        from ml.predict import load_predictor
    except ImportError as exc:
        raise ModelNotAvailableError(
            "ML prediction dependencies are not installed."
        ) from exc

    return load_predictor()


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


@app.exception_handler(ModelNotAvailableError)
async def handle_model_not_available_error(request, exc):
    logger.warning("Stockout model unavailable: %s", exc)
    return JSONResponse(
        status_code=503,
        content={"detail": str(exc)},
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
        "predict_stockout": "/predict-stockout",
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


def _find_deterministic_reference(
    facility: str,
    medicine: str,
) -> dict | None:
    """Return the deterministic classification for the same pair, if any.

    The reference lets the dashboard show ML evidence next to the
    authoritative rule-based result without conflating the two.
    """
    try:
        inventory, _, _ = run_analysis()
    except DataValidationError:
        logger.warning(
            "Deterministic reference unavailable for %s / %s",
            facility,
            medicine,
        )
        return None

    matches = inventory[
        (inventory["facility"].str.casefold() == facility.casefold())
        & (inventory["medicine"].str.casefold() == medicine.casefold())
    ]

    if matches.empty:
        return None

    row = matches.iloc[0]

    return {
        "stockout_risk": str(row["stockout_risk"]),
        "days_of_stock": round(float(row["days_of_stock"]), 1),
        "lead_time_days": round(float(row["lead_time_days"]), 1),
    }


@app.post(
    "/predict-stockout",
    response_model=StockoutPredictionResponse,
)
def predict_stockout(
    payload: StockoutPredictionRequest,
    predictor=Depends(get_stockout_predictor),
):
    """Predict a 30-day stockout for one facility/medicine pair.

    The prediction is supporting evidence. The deterministic rules in
    ``/inventory`` and ``/summary`` remain authoritative, and a human must
    review any operational action.
    """
    features = payload.model_dump()

    if features["month"] is None:
        features["month"] = date.today().month

    result = predictor.predict(features)

    return {
        "facility": payload.facility,
        "medicine": payload.medicine,
        "predicted_class": result.predicted_class,
        "prediction_label": result.prediction_label,
        "probability": result.probability,
        "probability_band": result.probability_band,
        "threshold": result.threshold,
        "model_id": result.model_id,
        "model_version": result.model_version,
        "deterministic_reference": _find_deterministic_reference(
            payload.facility,
            payload.medicine,
        ),
        "governance": {
            "data_type": "synthetic",
            "autonomous_action": False,
            "human_review_required": True,
            "note": (
                "ML output is predictive evidence only. Deterministic "
                "risk rules remain authoritative and an authorized "
                "supply-chain professional must review any action."
            ),
            "limitations": predictor.limitations,
        },
    }


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
