"""Evaluation helpers for the stockout models.

Selection is F2-first, because a missed stockout is usually costlier than
an unnecessary review. A precision floor prevents the model from simply
flagging every record.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    fbeta_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

DEFAULT_REPORT_PATH = (
    Path(__file__).resolve().parent / "artifacts" / "evaluation_report.json"
)

DEFAULT_THRESHOLDS = (0.5, 0.45, 0.4, 0.35, 0.3, 0.25, 0.2)
MIN_PRECISION = 0.40


def positive_probabilities(
    pipeline,
    features: pd.DataFrame,
) -> np.ndarray:
    """Return the predicted probability of the positive class."""
    probabilities = pipeline.predict_proba(features)
    classes = list(pipeline.classes_)

    if 1 not in classes:
        raise ValueError("The fitted model has no positive class.")

    return probabilities[:, classes.index(1)]


def evaluate_classifier(
    pipeline,
    features: pd.DataFrame,
    target: pd.Series,
    threshold: float = 0.5,
) -> dict:
    """Compute threshold-dependent metrics and the confusion matrix."""
    probabilities = positive_probabilities(pipeline, features)
    predictions = (probabilities >= threshold).astype(int)

    true_negative, false_positive, false_negative, true_positive = (
        confusion_matrix(target, predictions, labels=[0, 1]).ravel()
    )

    roc_auc = (
        float(roc_auc_score(target, probabilities))
        if target.nunique() == 2
        else None
    )

    return {
        "threshold": float(threshold),
        "accuracy": float(accuracy_score(target, predictions)),
        "precision": float(
            precision_score(target, predictions, zero_division=0)
        ),
        "recall": float(recall_score(target, predictions, zero_division=0)),
        "f1": float(f1_score(target, predictions, zero_division=0)),
        "f2": float(fbeta_score(target, predictions, beta=2, zero_division=0)),
        "roc_auc": roc_auc,
        "confusion_matrix": {
            "true_negative": int(true_negative),
            "false_positive": int(false_positive),
            "false_negative": int(false_negative),
            "true_positive": int(true_positive),
        },
        "support": {
            "negative": int((target == 0).sum()),
            "positive": int((target == 1).sum()),
        },
    }


def threshold_sweep(
    pipeline,
    features: pd.DataFrame,
    target: pd.Series,
    thresholds: tuple[float, ...] = DEFAULT_THRESHOLDS,
) -> list[dict]:
    """Evaluate the model across candidate decision thresholds."""
    return [
        evaluate_classifier(pipeline, features, target, threshold)
        for threshold in thresholds
    ]


def select_operating_point(
    sweep: list[dict],
    min_precision: float = MIN_PRECISION,
) -> dict:
    """Choose a threshold with high recall and a usable precision.

    F2 weights recall twice as heavily as precision, which matches the
    cost asymmetry of stockout screening. The precision floor keeps the
    alert volume usable. Ties break on recall, then F1. If no threshold
    meets the floor, fall back to the conventional 0.5 threshold rather
    than silently flagging everything.
    """
    eligible = [
        metrics for metrics in sweep if metrics["precision"] >= min_precision
    ]

    if not eligible:
        return next(
            (metrics for metrics in sweep if metrics["threshold"] == 0.5),
            sweep[0],
        )

    return sorted(
        eligible,
        key=lambda metrics: (
            -metrics["f2"],
            -metrics["recall"],
            -metrics["f1"],
            abs(metrics["threshold"] - 0.5),
        ),
    )[0]


def select_best_model(candidates: list[dict]) -> dict:
    """Pick the candidate with the best F2, then recall, then ROC-AUC."""
    if not candidates:
        raise ValueError("At least one candidate model is required.")

    return sorted(
        candidates,
        key=lambda candidate: (
            -candidate["operating_point"]["f2"],
            -candidate["operating_point"]["recall"],
            -(candidate["operating_point"]["roc_auc"] or 0.0),
            candidate["name"],
        ),
    )[0]


def format_report(report: dict) -> str:
    """Render a compact plain-text comparison of the evaluated models."""
    lines = [
        (
            f"{'Model':<22}{'Point':<12}{'Thr':>6}{'Prec':>8}"
            f"{'Rec':>8}{'F1':>8}{'F2':>8}{'AUC':>8}  TN/FP/FN/TP"
        ),
        "-" * 96,
    ]

    for name, result in report["models"].items():
        for label, metrics in (
            ("valid @0.50", result["validation_at_0_5"]),
            ("valid tuned", result["validation_operating_point"]),
            ("test tuned", result["test_at_operating_threshold"]),
        ):
            confusion = metrics["confusion_matrix"]
            roc_auc = metrics["roc_auc"]
            roc_auc_text = f"{roc_auc:.3f}" if roc_auc is not None else "n/a"
            lines.append(
                f"{name:<22}{label:<12}{metrics['threshold']:>6.2f}"
                f"{metrics['precision']:>8.3f}{metrics['recall']:>8.3f}"
                f"{metrics['f1']:>8.3f}{metrics['f2']:>8.3f}"
                f"{roc_auc_text:>8}"
                f"  {confusion['true_negative']}/"
                f"{confusion['false_positive']}/"
                f"{confusion['false_negative']}/"
                f"{confusion['true_positive']}"
            )

    lines.append("")
    lines.append(f"Selected model: {report['selected_model']}")
    lines.append(f"Selection policy: {report['selection_policy']}")
    lines.append(
        "Note: the model and threshold are selected on the validation "
        "split; the test rows are held out until the final estimate."
    )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Print the persisted stockout model evaluation report.",
    )
    parser.add_argument(
        "--report",
        type=Path,
        default=DEFAULT_REPORT_PATH,
        help="Path to evaluation_report.json.",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Print the raw JSON instead of a table.",
    )
    args = parser.parse_args(argv)

    if not args.report.exists():
        parser.error(
            f"Report not found: {args.report}. Run `python -m ml.train` first."
        )

    report = json.loads(args.report.read_text(encoding="utf-8"))

    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_report(report))

    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
