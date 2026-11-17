# Model card: 30-day stockout prediction

## Overview

| Field | Value |
| --- | --- |
| Model ID | `stockout-risk-30d` |
| Version | `1.0.0` |
| Task | Binary classification |
| Target | `stockout_within_30_days` |
| Selected algorithm | Random Forest |
| Decision threshold | `0.20` |
| Library | scikit-learn `1.9.1` |
| Artifact | `ml/artifacts/stockout_model.joblib` |
| Metadata | `ml/artifacts/model_metadata.json` |
| Report | `ml/artifacts/evaluation_report.json` |

## Intended use

The model estimates the probability that a facility/medicine pair will
experience a stockout at some point in the next 30 days. It is intended
for:

- adding predictive evidence beside the deterministic risk rules;
- helping an authorized supply-chain professional prioritize review;
- demonstrating a reproducible, local, low-cost ML workflow.

It is **not** intended to make autonomous operational decisions, place
orders, allocate stock, or replace the deterministic analysis.

## Out-of-scope use

- Real patient care or clinical decision-making.
- Production inventory control without local validation and human
  oversight.
- Any use with real facility data without retraining, calibration, and a
  prospective evaluation.
- Inferring causal effects of interventions.

## Data

The training data is synthetic. `ml/data_generation.py` starts from
`data/facilities.csv` (52 facility/medicine rows), simulates 12 monthly
observations per pair, and produces 624 rows with 117 positives (18.8%).

Features are recorded before the label is simulated. The label comes from
a separate forward 30-day simulation with stochastic demand,
replenishment arrivals, and supply disruption. Future draws are never
written to feature columns, which prevents target leakage.

## Features

Numeric: `month`, `current_stock`, `monthly_consumption`,
`recent_consumption_trend`, `lead_time_days`,
`historical_stockout_count`, `replenishment_frequency`, `expiry_days`,
`avg_daily_consumption`, `days_of_stock`.

Categorical: `facility`, `region`, `medicine`.

`avg_daily_consumption` and `days_of_stock` are derived deterministically
from raw inputs at both training and inference time.

## Preprocessing

A single scikit-learn `Pipeline` combines:

- numeric: median imputation, then `StandardScaler`;
- categorical: most-frequent imputation, then
  `OneHotEncoder(handle_unknown="ignore")`.

Preprocessing is fitted on training rows only and persisted with the
classifier.

## Split and selection

- 60/20/20 train/validation/test split.
- `StratifiedGroupKFold` grouped by facility/medicine pair, so a pair
  never spans splits.
- Model and threshold are chosen on validation.
- Selection is F2-first with a precision floor of `0.40`; ties break on
  recall, then ROC-AUC. Accuracy is reported but not used.

## Evaluation

Validation split:

| Model | Threshold | Precision | Recall | F1 | F2 | ROC-AUC |
| --- | --- | --- | --- | --- | --- | --- |
| Logistic Regression | 0.20 | 0.462 | 0.667 | 0.545 | 0.612 | 0.865 |
| Random Forest | 0.20 | 0.442 | 0.852 | 0.582 | 0.719 | 0.862 |

Held-out test split (one estimate):

| Model | Threshold | Precision | Recall | F1 | F2 | ROC-AUC | TN/FP/FN/TP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Logistic Regression | 0.20 | 0.594 | 0.792 | 0.679 | 0.742 | 0.924 | 95/13/5/19 |
| Random Forest | 0.20 | 0.621 | 0.750 | 0.679 | 0.720 | 0.921 | 97/11/6/18 |

The Random Forest at `0.20` was selected on validation F2. The test split
is small (132 rows, 24 positives), so the two models are statistically
close. Logistic Regression is a reasonable, more interpretable
alternative.

## Error trade-offs

Lowering the threshold raises recall and lowers precision. At `0.15`,
validation precision is `0.393`, below the `0.40` floor, so `0.20` is
the best F2 point that respects the policy. In this simulation, a false
negative means a missed stockout signal; a false positive means an
unnecessary review.

## Limitations

- Synthetic data only. Metrics describe the simulation, not real-world
  performance.
- Stylised demand, lead times, replenishment, and disruption.
- Small test split with wide uncertainty.
- Probabilities are not calibrated for operational thresholds.
- Unseen categories are ignored by the encoder.
- The model does not model transport cost, cold chain, safety stock, or
  FEFO rules.
- No temporal drift monitoring or retraining schedule is implemented.

## Ethical and governance notes

- Human review is required before any operational action.
- The API returns `governance.autonomous_action: false` and
  `human_review_required: true`.
- The deterministic risk classification remains authoritative.
- The artifact is loaded from a repository-controlled path; `joblib`
  deserialization is only acceptable because the artifact is trusted and
  never supplied by a request.

## Reproducing

```bash
python -m ml.data_generation
python -m ml.train
python -m ml.evaluate
```

Generation and model fitting use seed `42` by default. Artifacts are
written to `ml/artifacts/`.
