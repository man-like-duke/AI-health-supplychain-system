"""Load the persisted stockout model and produce predictions.

The model is loaded from a repository-controlled artifact path and cached
by file modification time. It is never trained per request and never
loaded from user input.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

import joblib
import pandas as pd

from ml.preprocessing import derive_features
from ml.schema import FEATURE_COLUMNS
from src.errors import ModelNotAvailableError

DEFAULT_MODEL_PATH = (
    Path(__file__).resolve().parent / "artifacts" / "stockout_model.joblib"
)
DEFAULT_METADATA_PATH = (
    Path(__file__).resolve().parent / "artifacts" / "model_metadata.json"
)

HIGH_PROBABILITY = 0.70
MODERATE_PROBABILITY = 0.40

DEFAULT_LIMITATIONS = (
    "Trained on synthetic data only; metrics do not describe real-world "
    "performance.",
    "Predictions are supporting evidence, not an autonomous decision.",
    "Human review is required before any operational action.",
)


@dataclass(frozen=True)
class StockoutPrediction:
    """A single prediction with the model provenance needed for review."""

    predicted_class: int
    prediction_label: str
    probability: float
    probability_band: str
    threshold: float
    model_id: str
    model_version: str


def probability_band(probability: float) -> str:
    """Map a probability to a presentation band for the dashboard.

    The band is a display aid. It is not the deterministic risk
    classification used by the rest of the application.
    """
    if probability >= HIGH_PROBABILITY:
        return "HIGH"
    if probability >= MODERATE_PROBABILITY:
        return "MODERATE"
    return "LOW"


class StockoutPredictor:
    """Thin wrapper around a fitted pipeline and its metadata."""

    def __init__(
        self,
        pipeline,
        metadata: Mapping[str, object],
    ) -> None:
        self._pipeline = pipeline
        self._metadata = dict(metadata)

    @property
    def model_id(self) -> str:
        return str(self._metadata.get("model_id", "unknown"))

    @property
    def model_version(self) -> str:
        return str(self._metadata.get("model_version", "unknown"))

    @property
    def threshold(self) -> float:
        return float(self._metadata.get("decision_threshold", 0.5))

    @property
    def limitations(self) -> list[str]:
        limitations = self._metadata.get("limitations")
        if isinstance(limitations, list) and limitations:
            return [str(item) for item in limitations]
        return list(DEFAULT_LIMITATIONS)

    def predict(
        self,
        features: Mapping[str, object],
    ) -> StockoutPrediction:
        """Predict from a single raw observation."""
        frame = derive_features(pd.DataFrame([dict(features)]))

        probabilities = self._pipeline.predict_proba(
            frame[list(FEATURE_COLUMNS)]
        )
        classes = list(self._pipeline.classes_)

        if 1 not in classes:
            raise ModelNotAvailableError(
                "The loaded model does not contain a positive class."
            )

        probability = float(probabilities[0, classes.index(1)])
        probability = min(1.0, max(0.0, probability))
        predicted_class = int(probability >= self.threshold)

        return StockoutPrediction(
            predicted_class=predicted_class,
            prediction_label=(
                "stockout_likely"
                if predicted_class == 1
                else "no_stockout_expected"
            ),
            probability=probability,
            probability_band=probability_band(probability),
            threshold=self.threshold,
            model_id=self.model_id,
            model_version=self.model_version,
        )


@lru_cache(maxsize=4)
def _load_cached(
    model_path: str,
    model_modified_time: float,
    metadata_path: str,
    metadata_modified_time: float,
) -> StockoutPredictor:
    # The path is fixed by application code, never by request input.
    # joblib is safe here only because the artifact is repository-owned.
    try:
        pipeline = joblib.load(model_path)
    except Exception as exc:
        raise ModelNotAvailableError(
            "The stockout model artifact could not be loaded. "
            "Retrain it with `python -m ml.train`."
        ) from exc

    try:
        metadata = json.loads(Path(metadata_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ModelNotAvailableError(
            "The stockout model metadata could not be loaded."
        ) from exc

    return StockoutPredictor(pipeline, metadata)


def load_predictor(
    model_path: Path = DEFAULT_MODEL_PATH,
    metadata_path: Path = DEFAULT_METADATA_PATH,
) -> StockoutPredictor:
    """Load the cached predictor, reloading when the artifacts change."""
    model_path = Path(model_path)
    metadata_path = Path(metadata_path)

    if not model_path.exists() or not metadata_path.exists():
        raise ModelNotAvailableError(
            "The stockout model artifact is unavailable. "
            "Train it with `python -m ml.train`."
        )

    return _load_cached(
        str(model_path.resolve()),
        model_path.stat().st_mtime,
        str(metadata_path.resolve()),
        metadata_path.stat().st_mtime,
    )


def clear_model_cache() -> None:
    """Clear the cached predictor (primarily useful in tests)."""
    _load_cached.cache_clear()


def predict_stockout(
    features: Mapping[str, object],
    predictor: StockoutPredictor | None = None,
) -> StockoutPrediction:
    """Convenience helper for scripts and tests."""
    return (predictor or load_predictor()).predict(features)
