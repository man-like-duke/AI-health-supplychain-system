"""Train, compare, and persist the stockout prediction models.

Run locally with::

    python -m ml.data_generation
    python -m ml.train
    python -m ml.evaluate

The selected pipeline (preprocessing + classifier) and its metadata are
written to ``ml/artifacts``. The API loads that artifact; it never trains
per request.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path

import joblib
import pandas as pd
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.linear_model import LogisticRegression

from ml.data_generation import (
    DEFAULT_HISTORY_PATH,
    GenerationConfig,
    write_stockout_history,
)
from ml.evaluate import (
    DEFAULT_THRESHOLDS,
    MIN_PRECISION,
    evaluate_classifier,
    format_report,
    select_best_model,
    select_operating_point,
    threshold_sweep,
)
from ml.preprocessing import (
    build_model_pipeline,
    split_train_validation_test,
    validate_training_frame,
)
from ml.schema import (
    CATEGORICAL_FEATURES,
    FEATURE_COLUMNS,
    NUMERIC_FEATURES,
    TARGET_COLUMN,
)

DEFAULT_ARTIFACTS_DIR = Path(__file__).resolve().parent / "artifacts"
MODEL_FILENAME = "stockout_model.joblib"
METADATA_FILENAME = "model_metadata.json"
REPORT_FILENAME = "evaluation_report.json"

MODEL_ID = "stockout-risk-30d"
MODEL_VERSION = "1.0.0"
DEFAULT_SEED = 42
DEFAULT_RF_ESTIMATORS = 200

SELECTION_POLICY = (
    "F2-first with a precision floor: choose the model and threshold with "
    "the highest validation F2 (recall weighted twice precision) among "
    "operating points whose precision is at least the configured floor; "
    "break ties on recall, then ROC-AUC. Accuracy is reported but is not "
    "the selection criterion."
)

MODEL_LIMITATIONS = [
    (
        "Trained only on synthetic data from ml/data_generation.py. "
        "Metrics describe this simulation, not real-world performance."
    ),
    (
        "The simulation is deliberately simpler than a real supply chain: "
        "demand, lead times, and replenishment follow stylised "
        "distributions."
    ),
    (
        "The threshold is chosen on a validation split and the test split "
        "is small, so the held-out metrics carry wide uncertainty."
    ),
    (
        "Facility, region, and medicine are one-hot encoded. Unseen "
        "categories at inference are ignored and rely on numeric features."
    ),
    (
        "Predicted probabilities are not calibrated for operational "
        "decision thresholds."
    ),
    (
        "The model predicts a 30-day stockout indicator only. It does not "
        "recommend transfers and does not replace the deterministic rules."
    ),
    (
        "Human review by an authorized supply-chain professional is "
        "required before any operational action."
    ),
]


def dataset_fingerprint(path: Path) -> str:
    """Return a SHA-256 digest of the dataset file."""
    digest = hashlib.sha256()

    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(65536), b""):
            digest.update(chunk)

    return digest.hexdigest()


def _build_estimators(seed: int, rf_n_estimators: int) -> dict:
    return {
        "logistic_regression": LogisticRegression(
            max_iter=1000,
            random_state=seed,
        ),
        "random_forest": RandomForestClassifier(
            n_estimators=rf_n_estimators,
            max_depth=10,
            min_samples_leaf=2,
            random_state=seed,
            n_jobs=-1,
        ),
    }


def train_and_evaluate(
    df: pd.DataFrame,
    artifacts_dir: Path = DEFAULT_ARTIFACTS_DIR,
    seed: int = DEFAULT_SEED,
    rf_n_estimators: int = DEFAULT_RF_ESTIMATORS,
    dataset_path: Path | None = None,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
    min_precision: float = MIN_PRECISION,
) -> dict:
    """Train both models, select one, and persist the artifacts."""
    validated = validate_training_frame(df)
    train, validation, test = split_train_validation_test(
        validated,
        seed=seed,
    )

    features_train = train[list(FEATURE_COLUMNS)]
    target_train = train[TARGET_COLUMN]
    features_validation = validation[list(FEATURE_COLUMNS)]
    target_validation = validation[TARGET_COLUMN]
    features_test = test[list(FEATURE_COLUMNS)]
    target_test = test[TARGET_COLUMN]

    models: dict[str, dict] = {}

    for name, estimator in _build_estimators(
        seed,
        rf_n_estimators,
    ).items():
        pipeline = build_model_pipeline(estimator)
        pipeline.fit(features_train, target_train)

        validation_baseline = evaluate_classifier(
            pipeline,
            features_validation,
            target_validation,
            threshold=0.5,
        )
        validation_sweep = threshold_sweep(
            pipeline,
            features_validation,
            target_validation,
            thresholds=thresholds,
        )
        operating_point = select_operating_point(
            validation_sweep,
            min_precision=min_precision,
        )
        test_metrics = evaluate_classifier(
            pipeline,
            features_test,
            target_test,
            threshold=operating_point["threshold"],
        )

        models[name] = {
            "pipeline": pipeline,
            "validation_at_0_5": validation_baseline,
            "threshold_sweep": validation_sweep,
            "validation_operating_point": operating_point,
            "test_at_operating_threshold": test_metrics,
        }

    selected_name = select_best_model(
        [
            {
                "name": name,
                "operating_point": result["validation_operating_point"],
            }
            for name, result in models.items()
        ]
    )["name"]
    selected = models[selected_name]

    artifacts_dir = Path(artifacts_dir)
    artifacts_dir.mkdir(parents=True, exist_ok=True)

    model_path = artifacts_dir / MODEL_FILENAME
    joblib.dump(selected["pipeline"], model_path)

    fingerprint = (
        dataset_fingerprint(dataset_path) if dataset_path is not None else None
    )

    metadata = {
        "model_id": MODEL_ID,
        "model_version": MODEL_VERSION,
        "algorithm": selected_name,
        "trained_at_utc": datetime.now(UTC).isoformat(timespec="seconds"),
        "random_state": seed,
        "decision_threshold": selected["validation_operating_point"][
            "threshold"
        ],
        "features": list(FEATURE_COLUMNS),
        "numeric_features": list(NUMERIC_FEATURES),
        "categorical_features": list(CATEGORICAL_FEATURES),
        "target": TARGET_COLUMN,
        "training_rows": int(len(train)),
        "validation_rows": int(len(validation)),
        "test_rows": int(len(test)),
        "class_balance": {
            "positive": int(validated[TARGET_COLUMN].sum()),
            "negative": int((validated[TARGET_COLUMN] == 0).sum()),
        },
        "split_strategy": (
            "StratifiedGroupKFold grouped by facility/medicine pair "
            "(60/20/20 train/validation/test)"
        ),
        "sklearn_version": sklearn.__version__,
        "metrics": selected["test_at_operating_threshold"],
        "validation_metrics": selected["validation_operating_point"],
        "validation_baseline_at_0_5": selected["validation_at_0_5"],
        "dataset": {
            "path": str(dataset_path) if dataset_path else None,
            "sha256": fingerprint,
        },
        "selection_policy": SELECTION_POLICY,
        "selection_metric": "f2",
        "limitations": list(MODEL_LIMITATIONS),
    }

    report = {
        "generated_at_utc": metadata["trained_at_utc"],
        "selected_model": selected_name,
        "selection_policy": SELECTION_POLICY,
        "selection_metric": "f2",
        "min_precision": min_precision,
        "models": {
            name: {
                "validation_at_0_5": result["validation_at_0_5"],
                "validation_operating_point": result[
                    "validation_operating_point"
                ],
                "test_at_operating_threshold": result[
                    "test_at_operating_threshold"
                ],
                "threshold_sweep": result["threshold_sweep"],
            }
            for name, result in models.items()
        },
    }

    (artifacts_dir / METADATA_FILENAME).write_text(
        json.dumps(metadata, indent=2),
        encoding="utf-8",
    )
    (artifacts_dir / REPORT_FILENAME).write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    return {
        "selected_model": selected_name,
        "metadata": metadata,
        "report": report,
        "model_path": model_path,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train and persist the stockout prediction model.",
    )
    parser.add_argument(
        "--data",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help="Synthetic history CSV (generated if missing).",
    )
    parser.add_argument(
        "--artifacts",
        type=Path,
        default=DEFAULT_ARTIFACTS_DIR,
        help="Directory for the model, metadata, and report.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for generation, splitting, and models.",
    )
    parser.add_argument(
        "--rf-estimators",
        type=int,
        default=DEFAULT_RF_ESTIMATORS,
        help="Number of trees in the Random Forest.",
    )
    parser.add_argument(
        "--generate",
        action="store_true",
        help="Regenerate the synthetic history before training.",
    )
    args = parser.parse_args(argv)

    data_path = Path(args.data)

    if args.generate or not data_path.exists():
        write_stockout_history(
            output_path=data_path,
            config=GenerationConfig(seed=args.seed),
        )

    df = pd.read_csv(data_path)

    result = train_and_evaluate(
        df,
        artifacts_dir=Path(args.artifacts),
        seed=args.seed,
        rf_n_estimators=args.rf_estimators,
        dataset_path=data_path,
    )

    print(format_report(result["report"]))
    print()
    print(f"Model artifact: {result['model_path']}")
    print(f"Metadata: {Path(args.artifacts) / METADATA_FILENAME}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
