"""Tests for synthetic generation, preprocessing, training, and inference."""

import json
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
import pytest
from sklearn.linear_model import LogisticRegression

from ml.data_generation import (
    DEFAULT_HISTORY_PATH,
    GenerationConfig,
    generate_stockout_history,
    write_stockout_history,
)
from ml.data_generation import (
    main as generate_main,
)
from ml.evaluate import (
    evaluate_classifier,
    format_report,
    positive_probabilities,
    select_best_model,
    select_operating_point,
    threshold_sweep,
)
from ml.evaluate import (
    main as evaluate_main,
)
from ml.predict import (
    DEFAULT_LIMITATIONS,
    StockoutPredictor,
    clear_model_cache,
    load_predictor,
    predict_stockout,
    probability_band,
)
from ml.preprocessing import (
    build_model_pipeline,
    build_preprocessor,
    derive_features,
    split_train_validation_test,
    validate_training_frame,
)
from ml.schema import FEATURE_COLUMNS, TARGET_COLUMN
from ml.train import (
    MODEL_FILENAME,
    REPORT_FILENAME,
    dataset_fingerprint,
    train_and_evaluate,
)
from ml.train import (
    main as train_main,
)
from src.errors import DataValidationError, ModelNotAvailableError


@pytest.fixture(scope="module")
def history() -> pd.DataFrame:
    return generate_stockout_history(
        config=GenerationConfig(seed=7, periods_per_pair=3)
    )


@pytest.fixture(scope="module")
def trained(history, tmp_path_factory):
    artifacts = tmp_path_factory.mktemp("artifacts")
    result = train_and_evaluate(
        history,
        artifacts_dir=artifacts,
        seed=7,
        rf_n_estimators=10,
    )
    return result, artifacts


@pytest.fixture()
def valid_row() -> dict:
    return {
        "facility": "Kaduna North",
        "region": "Kaduna",
        "medicine": "Amoxicillin",
        "month": 7,
        "current_stock": 180.0,
        "monthly_consumption": 450.0,
        "recent_consumption_trend": 1.1,
        "lead_time_days": 21.0,
        "historical_stockout_count": 2,
        "replenishment_frequency": 1.4,
        "expiry_days": 120.0,
    }


def test_generation_is_deterministic():
    config = GenerationConfig(seed=11, periods_per_pair=2)

    first = generate_stockout_history(config=config)
    second = generate_stockout_history(config=config)

    pd.testing.assert_frame_equal(first, second)
    assert len(first) == 52 * 2


def test_generation_varies_with_seed():
    first = generate_stockout_history(
        config=GenerationConfig(seed=1, periods_per_pair=2)
    )
    second = generate_stockout_history(
        config=GenerationConfig(seed=2, periods_per_pair=2)
    )

    assert not first.equals(second)


def test_generation_produces_binary_target_and_no_future_columns(history):
    assert set(history[TARGET_COLUMN].unique()).issubset({0, 1})
    assert TARGET_COLUMN in history.columns

    leaked = {
        column
        for column in history.columns
        if "future" in column or "outcome" in column
    }
    assert leaked == set()


def test_generation_rejects_invalid_inputs():
    with pytest.raises(DataValidationError, match="Missing required columns"):
        generate_stockout_history(
            base=pd.DataFrame({"facility": ["A"]}),
            config=GenerationConfig(periods_per_pair=1),
        )

    with pytest.raises(DataValidationError, match="empty"):
        generate_stockout_history(
            base=pd.DataFrame(
                columns=[
                    "facility",
                    "region",
                    "medicine",
                    "current_stock",
                    "monthly_consumption",
                    "lead_time_days",
                    "expiry_days",
                ]
            ),
            config=GenerationConfig(periods_per_pair=1),
        )


@pytest.mark.parametrize("periods", [0, -1])
def test_generation_requires_positive_periods(periods):
    with pytest.raises(DataValidationError, match="periods_per_pair"):
        generate_stockout_history(
            base=pd.read_csv(DEFAULT_HISTORY_PATH).head(1),
            config=GenerationConfig(periods_per_pair=periods),
        )


def test_generation_requires_positive_window():
    with pytest.raises(DataValidationError, match="prediction_window_days"):
        generate_stockout_history(
            base=pd.read_csv(DEFAULT_HISTORY_PATH).head(1),
            config=GenerationConfig(prediction_window_days=0),
        )


def test_write_stockout_history(tmp_path):
    output = tmp_path / "history.csv"

    written = write_stockout_history(
        output_path=output,
        config=GenerationConfig(seed=3, periods_per_pair=1),
    )

    assert output.exists()
    assert len(pd.read_csv(output)) == len(written) == 52


def test_generation_main_writes_csv(tmp_path, capsys):
    output = tmp_path / "generated.csv"

    assert generate_main(["--output", str(output), "--periods", "1"]) == 0
    assert output.exists()
    assert "Wrote 52 rows" in capsys.readouterr().out


def test_derive_features_adds_coverage_columns(valid_row):
    frame = derive_features(pd.DataFrame([valid_row]))

    assert frame.loc[0, "avg_daily_consumption"] == pytest.approx(15.0)
    assert frame.loc[0, "days_of_stock"] == pytest.approx(12.0)


@pytest.mark.parametrize(
    ("column", "value", "message"),
    [
        ("current_stock", -1, "current_stock"),
        ("monthly_consumption", 0, "monthly_consumption"),
        ("lead_time_days", 0, "lead_time_days"),
        ("expiry_days", -1, "expiry_days"),
        ("recent_consumption_trend", 0, "recent_consumption_trend"),
        ("replenishment_frequency", -1, "replenishment_frequency"),
        ("historical_stockout_count", -1, "historical_stockout_count"),
        ("month", 13, "month"),
        ("month", 0, "month"),
    ],
)
def test_derive_features_rejects_out_of_range_values(
    valid_row, column, value, message
):
    valid_row[column] = value

    with pytest.raises(DataValidationError, match=message):
        derive_features(pd.DataFrame([valid_row]))


def test_derive_features_rejects_missing_and_non_numeric(valid_row):
    missing = dict(valid_row)
    del missing["lead_time_days"]

    with pytest.raises(DataValidationError, match="Missing required columns"):
        derive_features(pd.DataFrame([missing]))

    valid_row["current_stock"] = "not-a-number"

    with pytest.raises(DataValidationError, match="must contain numeric"):
        derive_features(pd.DataFrame([valid_row]))


def test_derive_features_rejects_missing_numeric_values(valid_row):
    valid_row["current_stock"] = None

    with pytest.raises(DataValidationError, match="missing values"):
        derive_features(pd.DataFrame([valid_row]))


def test_derive_features_rejects_blank_categories(valid_row):
    valid_row["facility"] = "   "

    with pytest.raises(DataValidationError, match="cannot be blank"):
        derive_features(pd.DataFrame([valid_row]))


def test_derive_features_rejects_empty_frame():
    with pytest.raises(DataValidationError, match="empty"):
        derive_features(pd.DataFrame())


def test_validate_training_frame_requires_binary_target(valid_row):
    frame = pd.DataFrame([valid_row])
    frame[TARGET_COLUMN] = 2

    with pytest.raises(DataValidationError, match="only 0 and 1"):
        validate_training_frame(frame)


def test_validate_training_frame_requires_target(valid_row):
    with pytest.raises(DataValidationError, match="Missing required column"):
        validate_training_frame(pd.DataFrame([valid_row]))


def test_validate_training_frame_rejects_missing_target(valid_row):
    frame = pd.DataFrame([valid_row])
    frame[TARGET_COLUMN] = None

    with pytest.raises(DataValidationError, match="missing values"):
        validate_training_frame(frame)


def test_split_is_grouped_and_stratified(history):
    train, validation, test = split_train_validation_test(history, seed=7)

    assert len(train) + len(validation) + len(test) == len(history)

    def pairs(frame):
        return set(zip(frame["facility"], frame["medicine"], strict=True))

    train_pairs = pairs(train)
    validation_pairs = pairs(validation)
    test_pairs = pairs(test)

    assert train_pairs.isdisjoint(validation_pairs)
    assert train_pairs.isdisjoint(test_pairs)
    assert validation_pairs.isdisjoint(test_pairs)

    for split in (train, validation, test):
        assert split[TARGET_COLUMN].nunique() == 2


def test_split_requires_three_pairs(history):
    one_pair = history[
        (history["facility"] == history["facility"].iloc[0])
        & (history["medicine"] == history["medicine"].iloc[0])
    ]

    with pytest.raises(DataValidationError, match="At least three"):
        split_train_validation_test(one_pair)


def test_preprocessor_ignores_unseen_categories(history, valid_row):
    train, _, _ = split_train_validation_test(history, seed=7)
    pipeline = build_model_pipeline(LogisticRegression(max_iter=200))
    pipeline.fit(
        train[list(FEATURE_COLUMNS)],
        train[TARGET_COLUMN],
    )

    unseen = dict(valid_row)
    unseen["facility"] = "Unseen Facility"
    unseen["region"] = "Unseen Region"
    unseen["medicine"] = "Unseen Medicine"

    probabilities = pipeline.predict_proba(
        derive_features(pd.DataFrame([unseen]))[list(FEATURE_COLUMNS)]
    )

    assert probabilities.shape == (1, 2)
    assert 0.0 <= float(probabilities[0, 1]) <= 1.0


def test_build_preprocessor_declares_feature_contract():
    preprocessor = build_preprocessor()

    assert [name for name, _, _ in preprocessor.transformers] == [
        "numeric",
        "categorical",
    ]


def test_evaluate_classifier_reports_confusion_matrix(history, trained):
    result, artifacts = trained
    predictor = load_predictor(
        artifacts / MODEL_FILENAME,
        artifacts / "model_metadata.json",
    )

    _, validation, _ = split_train_validation_test(history, seed=7)
    metrics = evaluate_classifier(
        predictor._pipeline,
        validation[list(FEATURE_COLUMNS)],
        validation[TARGET_COLUMN],
        threshold=0.5,
    )

    confusion = metrics["confusion_matrix"]
    assert confusion["true_negative"] + confusion[
        "false_positive"
    ] + confusion["false_negative"] + confusion["true_positive"] == len(
        validation
    )
    assert 0.0 <= metrics["f2"] <= 1.0
    assert 0.0 <= metrics["roc_auc"] <= 1.0
    assert metrics["support"]["positive"] == int(
        validation[TARGET_COLUMN].sum()
    )


def test_positive_probabilities_require_positive_class(history):
    class _NegativeOnly:
        classes_ = [0]

        def predict_proba(self, features):
            return pd.DataFrame({0: [1.0] * len(features)}).to_numpy()

    with pytest.raises(ValueError, match="positive class"):
        positive_probabilities(
            _NegativeOnly(),
            history[list(FEATURE_COLUMNS)].head(2),
        )


def test_threshold_sweep_returns_requested_points(history, trained):
    result, artifacts = trained
    predictor = load_predictor(
        artifacts / MODEL_FILENAME,
        artifacts / "model_metadata.json",
    )

    _, validation, _ = split_train_validation_test(history, seed=7)
    sweep = threshold_sweep(
        predictor._pipeline,
        validation[list(FEATURE_COLUMNS)],
        validation[TARGET_COLUMN],
        thresholds=(0.5, 0.3),
    )

    assert [point["threshold"] for point in sweep] == [0.5, 0.3]


def _point(threshold, precision, recall, f1, f2, roc_auc=0.8):
    return {
        "threshold": threshold,
        "precision": precision,
        "recall": recall,
        "f1": f1,
        "f2": f2,
        "roc_auc": roc_auc,
    }


def test_select_operating_point_prefers_f2_within_precision_floor():
    sweep = [
        _point(0.5, 0.9, 0.3, 0.45, 0.35),
        _point(0.3, 0.5, 0.8, 0.62, 0.72),
        _point(0.2, 0.35, 0.95, 0.51, 0.74),
    ]

    selected = select_operating_point(sweep, min_precision=0.4)

    assert selected["threshold"] == 0.3


def test_select_operating_point_falls_back_to_half():
    sweep = [
        _point(0.5, 0.2, 0.9, 0.33, 0.55),
        _point(0.3, 0.1, 0.95, 0.18, 0.4),
    ]

    selected = select_operating_point(sweep, min_precision=0.9)

    assert selected["threshold"] == 0.5


def test_select_best_model_breaks_ties_and_requires_candidates():
    first = {"name": "a", "operating_point": _point(0.2, 0.5, 0.8, 0.6, 0.7)}
    second = {
        "name": "b",
        "operating_point": _point(0.2, 0.5, 0.8, 0.6, 0.7, roc_auc=0.9),
    }

    assert select_best_model([first, second])["name"] == "b"

    with pytest.raises(ValueError, match="At least one"):
        select_best_model([])


def test_train_and_evaluate_persists_artifacts(trained):
    result, artifacts = trained
    metadata = json.loads(
        (artifacts / "model_metadata.json").read_text(encoding="utf-8")
    )
    report = json.loads(
        (artifacts / REPORT_FILENAME).read_text(encoding="utf-8")
    )

    assert (artifacts / MODEL_FILENAME).exists()
    assert result["selected_model"] in report["models"]
    assert metadata["algorithm"] == result["selected_model"]
    assert metadata["target"] == TARGET_COLUMN
    assert metadata["decision_threshold"] in {0.2, 0.25, 0.3, 0.35, 0.4, 0.5}
    assert metadata["training_rows"] > metadata["validation_rows"] > 0
    assert metadata["test_rows"] > 0
    assert metadata["metrics"]["threshold"] == metadata["decision_threshold"]
    assert 0.0 <= metadata["metrics"]["f2"] <= 1.0
    assert metadata["limitations"]
    assert report["selection_metric"] == "f2"
    assert set(report["models"]) == {"logistic_regression", "random_forest"}

    for _name, model_report in report["models"].items():
        assert model_report["validation_operating_point"]["threshold"] in {
            0.2,
            0.25,
            0.3,
            0.35,
            0.4,
            0.5,
        }


def test_format_report_renders_selected_model(trained):
    result, _ = trained

    text = format_report(result["report"])

    assert "Selected model" in text
    assert "validation" in text.lower()
    assert result["selected_model"] in text


def test_train_main_generates_data_and_artifacts(tmp_path, capsys):
    data_path = tmp_path / "history.csv"
    artifacts = tmp_path / "artifacts"

    assert (
        train_main(
            [
                "--data",
                str(data_path),
                "--artifacts",
                str(artifacts),
                "--seed",
                "3",
                "--rf-estimators",
                "5",
                "--generate",
            ]
        )
        == 0
    )

    assert data_path.exists()
    assert (artifacts / MODEL_FILENAME).exists()
    output = capsys.readouterr().out
    assert "Selected model" in output
    assert "Model artifact" in output


def test_evaluate_main_prints_report(trained, capsys):
    _, artifacts = trained
    report_path = artifacts / REPORT_FILENAME

    assert evaluate_main(["--report", str(report_path)]) == 0
    assert "Selected model" in capsys.readouterr().out

    assert evaluate_main(["--report", str(report_path), "--json"]) == 0
    assert "selected_model" in capsys.readouterr().out


def test_evaluate_main_rejects_missing_report(tmp_path):
    with pytest.raises(SystemExit):
        evaluate_main(["--report", str(tmp_path / "missing.json")])


def test_dataset_fingerprint_changes_with_content(tmp_path):
    first = tmp_path / "first.csv"
    second = tmp_path / "second.csv"
    first.write_text("a,b\n1,2\n", encoding="utf-8")
    second.write_text("a,b\n1,3\n", encoding="utf-8")

    assert dataset_fingerprint(first) == dataset_fingerprint(first)
    assert dataset_fingerprint(first) != dataset_fingerprint(second)


@pytest.mark.parametrize(
    ("probability", "expected"),
    [
        (0.0, "LOW"),
        (0.39, "LOW"),
        (0.4, "MODERATE"),
        (0.69, "MODERATE"),
        (0.7, "HIGH"),
        (1.0, "HIGH"),
    ],
)
def test_probability_band_thresholds(probability, expected):
    assert probability_band(probability) == expected


def test_predictor_defaults_when_metadata_is_sparse():
    class _Constant:
        classes_ = [0, 1]

        def predict_proba(self, features):
            return np.array([[0.25, 0.75] for _ in range(len(features))])

    predictor = StockoutPredictor(_Constant(), {})

    assert predictor.model_id == "unknown"
    assert predictor.model_version == "unknown"
    assert predictor.threshold == 0.5
    assert predictor.limitations == list(DEFAULT_LIMITATIONS)

    prediction = predictor.predict(
        {
            "facility": "A",
            "region": "B",
            "medicine": "C",
            "month": 1,
            "current_stock": 10,
            "monthly_consumption": 30,
            "recent_consumption_trend": 1.0,
            "lead_time_days": 7,
            "historical_stockout_count": 0,
            "replenishment_frequency": 1.0,
            "expiry_days": 90,
        }
    )

    assert prediction.predicted_class == 1
    assert prediction.probability == pytest.approx(0.75)
    assert prediction.probability_band == "HIGH"


def test_predictor_rejects_missing_positive_class(valid_row):
    class _NegativeOnly:
        classes_ = [0]

        def predict_proba(self, features):
            return [[1.0] for _ in range(len(features))]

    predictor = StockoutPredictor(_NegativeOnly(), {})

    with pytest.raises(ModelNotAvailableError, match="positive class"):
        predictor.predict(valid_row)


def test_load_predictor_returns_cached_artifact():
    clear_model_cache()

    first = load_predictor()
    second = load_predictor()

    assert first is second
    assert first.model_id
    assert first.model_version


def test_load_predictor_rejects_missing_artifacts(tmp_path):
    clear_model_cache()

    with pytest.raises(ModelNotAvailableError, match="unavailable"):
        load_predictor(
            tmp_path / "missing.joblib",
            tmp_path / "missing.json",
        )


def test_load_predictor_rejects_corrupt_artifact(tmp_path):
    clear_model_cache()
    model_path = tmp_path / "model.joblib"
    metadata_path = tmp_path / "metadata.json"
    model_path.write_text("not a joblib artifact", encoding="utf-8")
    metadata_path.write_text("{}", encoding="utf-8")

    with pytest.raises(ModelNotAvailableError, match="could not be loaded"):
        load_predictor(model_path, metadata_path)


def test_load_predictor_rejects_corrupt_metadata(tmp_path):
    clear_model_cache()
    model_path = tmp_path / "model.joblib"
    metadata_path = tmp_path / "metadata.json"
    joblib.dump({"dummy": True}, model_path)
    metadata_path.write_text("{not json", encoding="utf-8")

    with pytest.raises(ModelNotAvailableError, match="metadata"):
        load_predictor(model_path, metadata_path)


def test_predict_stockout_helper_returns_prediction(valid_row):
    prediction = predict_stockout(valid_row)

    assert prediction.predicted_class in {0, 1}
    assert 0.0 <= prediction.probability <= 1.0
    assert prediction.model_id == "stockout-risk-30d"


def test_predict_rejects_missing_features():
    with pytest.raises(DataValidationError, match="Missing required columns"):
        predict_stockout({"facility": "A"})


def test_artifacts_directory_contains_committed_model():
    artifacts = Path(__file__).resolve().parent.parent / "ml" / "artifacts"

    assert (artifacts / MODEL_FILENAME).exists()
    assert (artifacts / "model_metadata.json").exists()
    assert (artifacts / REPORT_FILENAME).exists()
