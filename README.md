# AI Health Supply Chain Decision Support

A small, deterministic decision-support service for synthetic health
supply-chain inventory risk and redistribution analysis. It identifies
stockout and expiry risk, proposes redistribution candidates, and can
optionally ask Gemini to explain the results in plain language. A browser
dashboard at `/dashboard` gives operators a filterable view of the same
results.

A separate Scikit-learn model adds a 30-day stockout probability as
predictive evidence. The deterministic rules stay authoritative, and the
model never takes an action.

> **This is a prototype using synthetic data.** It contains no real
> patient or facility data. Recommendations are analytical candidates
> only and must be reviewed and approved by an authorized health-program
> or supply-chain professional. The system never takes autonomous
> operational action.

## What it does

- Calculates days of stock from current stock and monthly consumption.
- Classifies stockout risk against each facility's lead time.
- Classifies expiry risk against the remaining shelf life.
- Finds redistribution candidates between facilities holding the same
  medicine, while protecting each source facility's own reserve.
- Allocates transfers greedily so a destination gap or source surplus is
  never promised more than once.
- Builds a structured decision summary with governance metadata.
- Predicts a 30-day stockout probability with a persisted Scikit-learn
  model trained on reproducible synthetic history.
- Optionally produces a constrained LLM explanation of the summary.
- Serves an operator dashboard with a risk matrix, shareable filters,
  CSV export, an ML prediction panel, and an explanation panel.

## Project structure

```text
.github/
  workflows/
    ci.yml              Lint, format, and test gate
    security.yml        Secrets, SAST, dependency audit, and SBOM
    codeql.yml          CodeQL analysis for Python and JavaScript
  dependabot.yml        Weekly dependency and action updates
.semgrep/rules.yml      Project-specific static-analysis rules
.gitleaks.toml          Narrow secret-scanning allowlist
.pre-commit-config.yaml Local secret and lint hooks
data/facilities.csv     Synthetic facility inventory dataset
data/synthetic_stockout_history.csv
                        Reproducible synthetic monthly history for ML
ml/
  __init__.py           Package marker
  schema.py             Canonical feature and target columns
  data_generation.py    Synthetic history and forward-window target
  preprocessing.py      Validation, derived features, sklearn pipeline
  evaluate.py           Metrics, F2 threshold selection, report
  train.py              Train, compare, select, and persist the model
  predict.py            Cached artifact loading and inference
  artifacts/            Persisted model, metadata, and evaluation report
  MODEL_CARD.md         Intended use, metrics, and limitations
src/
  api.py                FastAPI application and response models
  config.py             Thresholds, weights, and tunable assumptions
  data.py               CSV loading and strict validation
  decisions.py          Structured decision-support summary
  errors.py             Domain-specific exception types
  llm.py                Prompt construction, Gemini provider, guardrails
  main.py               CLI entry point
  pipeline.py           Pipeline composition and result caching
  recommendations.py    Redistribution allocation and ranking
  risk.py               Coverage and risk classification
  serialization.py      JSON-safe DataFrame conversion
static/
  index.html            Operator dashboard shell
  styles.css            Dashboard themes, layout, and print styles
  app.js                Dashboard data loading, filters, and CSV export
tests/                  Unit and API tests
SECURITY.md             Vulnerability disclosure and suppression policy
```

## Quick start

Requires Python 3.12+ (the project has been run on 3.14).

```bash
python -m venv .venv
# Windows
.venv\Scripts\activate
# macOS/Linux
source .venv/bin/activate

pip install -r requirements.txt
```

### Configuration

Copy `.env.example` to `.env` and set the Gemini key if you want the
explanation endpoint:

```bash
GEMINI_API_KEY=your-gemini-api-key
```

Optional variables:

| Variable | Default | Purpose |
| --- | --- | --- |
| `GEMINI_MODEL` | `gemini-3.1-flash-lite` | Gemini model name |
| `GEMINI_TIMEOUT_MS` | `30000` | Request timeout |
| `GEMINI_MAX_RETRIES` | `2` | Retry attempts |
| `FACILITY_DATA_PATH` | `data/facilities.csv` | Alternate dataset |

All endpoints except `/explanation` work without a key.

### Run the API

```bash
uvicorn src.api:app --reload
```

Open <http://127.0.0.1:8000/docs> for the interactive OpenAPI docs and
<http://127.0.0.1:8000/dashboard> for the operator dashboard.

### Open the dashboard

Browse to <http://127.0.0.1:8000/dashboard>. The dashboard is plain
HTML, CSS, and JavaScript served by the same FastAPI app, so there is no
Node build step and no separate frontend deployment.

It provides:

- KPI cards for facilities, CRITICAL/HIGH stockouts, expiry risks, and
  allocated candidates.
- A facility-by-medicine risk matrix with coverage bars measured against
  `2 × lead_time_days` and expiry-risk labels.
- Redistribution candidates showing the transfer, gap remaining after
  allocation, protected source surplus, batch expiry, score, and the
  human-review requirement.
- Region, medicine, stockout-risk, and free-text filters. Filter state is
  stored in the URL, for example
  `/dashboard?region=Lagos&risk=CRITICAL`.
- CSV export of the current filtered inventory and candidates.
- An ML prediction panel with three separate cards: deterministic risk,
  ML prediction, and a decision-support recommendation. The model never
  decides or acts.
- A "Generate explanation" panel with loading, error (`503`), and
  guardrail-warning states.
- Light/dark themes, responsive layouts, keyboard focus styles, and
  print styles.

The dashboard calls `/summary`, `/inventory`, `/recommendations`,
`/predict-stockout`, and `/explanation`; it never recalculates risk or
runs a model in the browser.

#### Dashboard URL parameters

| Parameter | Values | Applies to |
| --- | --- | --- |
| `region` | Any dataset region | Inventory rows; candidates touching that region |
| `medicine` | Any dataset medicine | Inventory and candidates |
| `risk` | `CRITICAL`, `HIGH`, `MEDIUM`, `LOW` | Inventory stockout risk; candidate destination risk |
| `q` | Free text | Facility, region, medicine, source, and destination names |

Parameters are optional and case-insensitive. Unknown values are
discarded, and active filters are written back to the URL so a view can
be bookmarked or shared.

CSV exports contain the rows visible after filters are applied.

The dashboard is read-only: it does not approve, execute, or persist
recommendations. The explanation panel requires `GEMINI_API_KEY`; without
it, the panel shows the API's `503` message and the rest of the dashboard
continues to work.

### Run the CLI

```bash
python -m src.main
python -m src.main --json
python -m src.main --data path/to/facilities.csv --json
```

## API

| Method | Path | Description |
| --- | --- | --- |
| `GET` | `/` | Service metadata |
| `GET` | `/dashboard` | Operator dashboard (HTML) |
| `GET` | `/static/*` | Dashboard CSS and JavaScript |
| `GET` | `/health` | Health check |
| `GET` | `/inventory?region=&medicine=&stockout_risk=` | Per-facility inventory risk |
| `GET` | `/recommendations?medicine=&source_facility=&destination_facility=` | Allocated redistribution candidates |
| `GET` | `/summary` | Decision summary and governance metadata |
| `POST` | `/predict-stockout` | 30-day stockout probability for one pair |
| `GET` | `/explanation?refresh=false` | LLM explanation of the summary |

Filters are case-insensitive and optional. The `/dashboard` and
`/static/*` routes are browser-facing; the remaining routes return JSON.

Example:

```bash
curl http://127.0.0.1:8000/summary
curl "http://127.0.0.1:8000/inventory?region=Lagos"
curl "http://127.0.0.1:8000/explanation?refresh=true"
```

`/explanation` caches provider responses in memory for identical prompts.
Pass `?refresh=true` to bypass the cache. If the key is missing the
endpoint returns `503`; data validation failures return `422`.

## Analysis model

### Days of stock

```text
days_of_stock = current_stock / (monthly_consumption / 30)
```

### Stockout risk

| Classification | Condition |
| --- | --- |
| `CRITICAL` | `days_of_stock < lead_time_days` |
| `HIGH` | `< 1.5 × lead_time_days` |
| `MEDIUM` | `< 2 × lead_time_days` |
| `LOW` | otherwise |

### Expiry risk

| Classification | Condition |
| --- | --- |
| `HIGH` | `expiry_days < days_of_stock` (stock outlasts shelf life) |
| `MEDIUM` | shelf-life margin after consumption is under 30 days |
| `LOW` | comfortable margin, or no stock to expire |

### Redistribution

1. A destination is a facility with `HIGH` or `CRITICAL` stockout risk and
   a coverage gap against a target of `2 × lead_time_days`.
2. A source must hold the same medicine and keep its own reserve of
   `2 × lead_time_days`; only the surplus is usable.
3. Sources are ranked by a weighted score:
   - 50% gap coverage,
   - 30% surplus cushion (beyond twice the gap),
   - 20% expiry urgency (stock expiring sooner is preferred).
4. Transfers are allocated greedily, highest-risk destinations first.
   Both the destination gap and source surplus are decremented, so the
   same stock cannot be promised twice. A transfer is also capped by the
   source batch's remaining shelf life, and transfers below one day are
   skipped.

All thresholds and weights live in `src/config.py`.

## Machine learning stockout prediction

### Problem

The deterministic rules answer "how many days of cover does this pair
have right now?" The ML model answers a different, complementary
question: **what is the probability that this facility/medicine pair
records a stockout at some point in the next 30 days?** It is predictive
evidence for human review, not a replacement for the rules.

### Dataset and target

`data/synthetic_stockout_history.csv` is generated from the 52-row
facility snapshot. Each facility/medicine pair gets 12 monthly
observations, producing 624 rows with 117 positives (18.8%).

The target `stockout_within_30_days` is produced by a **separate forward
simulation** after the features are recorded. That simulation draws
future demand, future replenishment arrivals, and a possible supply
disruption. Future draws are never written to a feature column, so the
label cannot leak into the inputs.

```bash
python -m ml.data_generation
```

Generation is deterministic for a fixed seed (`42` by default) and
requires no paid service, GPU, or cloud runtime.

### Features

Features are observed at prediction time only:

| Feature | Type | Meaning |
| --- | --- | --- |
| `month` | numeric | Calendar month (1–12) |
| `current_stock` | numeric | Units on hand |
| `monthly_consumption` | numeric | Units consumed per month |
| `recent_consumption_trend` | numeric | Recent demand ratio |
| `lead_time_days` | numeric | Supplier lead time |
| `historical_stockout_count` | numeric | Prior stockouts for the pair |
| `replenishment_frequency` | numeric | Expected replenishments per month |
| `expiry_days` | numeric | Remaining shelf life |
| `avg_daily_consumption` | derived | `monthly_consumption / 30` |
| `days_of_stock` | derived | `current_stock / avg_daily_consumption` |
| `facility`, `region`, `medicine` | categorical | One-hot encoded identifiers |

Derived columns are recomputed from raw inputs at both training and
inference time, so the definitions cannot drift.

### Preprocessing and split

- A single scikit-learn `Pipeline` contains a `ColumnTransformer`:
  median imputation plus `StandardScaler` for numeric features, and
  most-frequent imputation plus `OneHotEncoder(handle_unknown="ignore")`
  for categorical features.
- Preprocessing is fitted **inside** the pipeline on training rows only.
- Rows are split 60/20/20 with `StratifiedGroupKFold`, grouped by
  facility/medicine pair. A pair appears in exactly one split, so
  adjacent months cannot inflate the score.
- Model and threshold are selected on the validation split. The test
  split is touched once for the final estimate.

### Models and selection

Two candidates are trained:

1. Logistic Regression (baseline, interpretable).
2. Random Forest (200 trees, `max_depth=10`, `min_samples_leaf=2`).

The selection policy is **F2-first with a precision floor**:

1. Sweep decision thresholds from `0.50` down to `0.20`.
2. Keep operating points with precision at least `0.40`.
3. Choose the highest validation F2, which weights recall twice as
   heavily as precision.
4. Break ties on recall, then ROC-AUC.

Accuracy is reported but is not used to select the model. Missing a
stockout is treated as costlier than an unnecessary review, while the
precision floor keeps alert volume usable.

### Results

Validation split (selection):

| Model | Threshold | Precision | Recall | F1 | F2 | ROC-AUC |
| --- | --- | --- | --- | --- | --- | --- |
| Logistic Regression | 0.20 | 0.462 | 0.667 | 0.545 | 0.612 | 0.865 |
| Random Forest | 0.20 | 0.442 | 0.852 | 0.582 | **0.719** | 0.862 |

Held-out test split (single estimate):

| Model | Threshold | Precision | Recall | F1 | F2 | ROC-AUC | TN/FP/FN/TP |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Logistic Regression | 0.20 | 0.594 | 0.792 | 0.679 | 0.742 | 0.924 | 95/13/5/19 |
| Random Forest | 0.20 | 0.621 | 0.750 | 0.679 | 0.720 | 0.921 | 97/11/6/18 |

**Selected model:** Random Forest at threshold `0.20`, chosen on
validation F2. The test split is small (132 rows, 24 positives), so the
difference between the two models on test is well within noise.
Logistic Regression remains a reasonable, more interpretable
alternative.

The false-negative/false-positive trade-off is explicit: lowering the
threshold raises recall but lowers precision. At `0.15`, validation
precision falls to `0.393`, below the `0.40` floor, so `0.20` is the
best F2 operating point that respects the policy.

### Train, evaluate, and predict

```bash
python -m ml.data_generation   # regenerate the synthetic history
python -m ml.train             # fit both models, select, persist artifacts
python -m ml.evaluate          # print the persisted evaluation report
```

Artifacts are written to `ml/artifacts/`:

- `stockout_model.joblib` — the fitted preprocessing + classifier pipeline.
- `model_metadata.json` — model id/version, threshold, features, split
  sizes, metrics, dataset SHA-256, and limitations.
- `evaluation_report.json` — both models, threshold sweeps, and the
  held-out estimate.

The API loads this artifact once and caches it by file modification time.
It never trains per request.

### API integration

```bash
curl -X POST http://127.0.0.1:8000/predict-stockout \
  -H "Content-Type: application/json" \
  -d '{
    "facility": "Kaduna North",
    "region": "Kaduna",
    "medicine": "Amoxicillin",
    "month": 7,
    "current_stock": 180,
    "monthly_consumption": 450,
    "lead_time_days": 21,
    "expiry_days": 120,
    "recent_consumption_trend": 1.1,
    "historical_stockout_count": 2,
    "replenishment_frequency": 1.4
  }'
```

The response includes the predicted class, label, probability, display
band (`HIGH >= 0.70`, `MODERATE >= 0.40`, else `LOW`), decision
threshold, model id/version, an optional deterministic reference for the
same pair, and governance metadata. Inputs are validated by Pydantic;
unknown fields are rejected. A missing or unloadable artifact returns
`503`.

### Safeguards and limitations

- Synthetic data only. Every metric describes this simulation, not
  real-world clinical or operational performance.
- The deterministic classification remains authoritative. ML output is
  supporting evidence.
- The model never orders, transfers, or allocates stock, and
  `governance.autonomous_action` is always `false`.
- Human review by an authorized supply-chain professional is required.
- The simulation is stylised: demand, lead times, and replenishment do
  not capture real seasonality, policy, or cold-chain constraints.
- Probabilities are not calibrated for operational thresholds.
- The test split is small, so held-out metrics carry wide uncertainty.
- Unseen facilities or medicines at inference are ignored by the
  encoder; prediction then relies mainly on numeric features.

See [ml/MODEL_CARD.md](ml/MODEL_CARD.md) for the model card.

## Data dictionary

The bundled dataset is synthetic and deliberately sparse: 12 facilities
across 12 regions, 7 medicines, and 52 facility/medicine rows. Not every
facility stocks every medicine.

`data/facilities.csv`:

| Column | Meaning |
| --- | --- |
| `facility` | Facility name |
| `region` | Region or state |
| `medicine` | Medicine name |
| `current_stock` | Units currently on hand |
| `monthly_consumption` | Units consumed per month |
| `lead_time_days` | Supplier lead time in days |
| `expiry_days` | Remaining shelf life in days |

`current_stock` and `monthly_consumption` are in medicine-specific units
(tablets, sachets, vials), so days of stock are only compared within the
same medicine.

`data/synthetic_stockout_history.csv` adds the ML history:

| Column | Meaning |
| --- | --- |
| `facility`, `region`, `medicine` | Pair identifiers |
| `month` | Calendar month |
| `current_stock`, `monthly_consumption` | Observed stock and demand |
| `recent_consumption_trend` | Ratio versus the previous month |
| `lead_time_days`, `expiry_days` | Observed supply constraints |
| `historical_stockout_count` | Prior stockouts for the pair |
| `replenishment_frequency` | Expected replenishments per month |
| `avg_daily_consumption`, `days_of_stock` | Derived coverage features |
| `stockout_within_30_days` | Binary forward-simulation target |

Validation rejects missing columns, non-numeric values, missing or blank
fields, negative values, zero consumption, zero lead time, and duplicate
facility/medicine rows.

## Governance and limitations

- Synthetic data only; no real patient information.
- The deterministic layers make the classifications; the LLM only
  explains them and the ML model only adds a probability.
- The LLM receives a constrained prompt and its output is checked for
  CRITICAL/HIGH reporting and a human-review statement. Warnings are
  returned in `governance.guardrail_warnings`.
- The ML model never acts autonomously. The dashboard shows
  deterministic risk, ML prediction, and a decision-support
  recommendation as separate cards.
- Model artifacts are repository-controlled and loaded with `joblib`;
  the path is fixed in code and never comes from request input.
- Days of stock are treated as comparable across facilities. Production
  use should convert transfers to units using monthly consumption.
- The model does not yet include transport cost, cold-chain constraints,
  safety stock/service levels, or FEFO (first-expiry-first-out) rules.
- No authentication, rate limiting, or CORS is configured. Add these
  before exposing the service beyond a trusted environment.

## Testing

```bash
python -m pytest
# with coverage
pip install -r requirements-dev.txt
python -m pytest --cov=src --cov=ml
```

Tests cover validation, risk boundaries, allocation limits, decision
summary structure, prompt/guardrail behavior, provider caching and
errors, API status mapping, synthetic generation determinism, feature
derivation, grouped splits, preprocessing, training and selection,
artifact persistence and loading, prediction ranges, and the prediction
endpoint. CI enforces a 90% coverage floor across `src` and `ml`.

## Security pipeline

The repository runs a DevSecOps pipeline on every push to `main` and every
pull request, plus a weekly scheduled run for newly disclosed issues.

```text
push / pull request
   ├── CI ──────────────── ruff, format, pytest (90% coverage floor)
   ├── Gitleaks ────────── secret scanning (full git history)
   ├── Semgrep ─────────── SAST (p/python, p/owasp-top-ten, custom rules)
   ├── pip-audit ───────── runtime and development dependencies
   ├── Dependency Review ─ blocks new high/critical dependencies (PRs)
   ├── CodeQL ──────────── dataflow SAST for Python and JavaScript
   └── SBOM ────────────── CycloneDX artifact
```

| Check | Tool | Gate |
| --- | --- | --- |
| Secrets | Gitleaks | Any finding in git history |
| SAST | Semgrep | `ERROR`-severity findings |
| Dependencies | pip-audit | Any known vulnerability |
| Dependency changes | Dependency Review | High or critical severity in a PR |
| Deep SAST | CodeQL | Alerts under Security → Code scanning |
| Supply chain | CycloneDX | SBOM generation or validation failure |

Gitleaks comments on pull requests and fails the job. Rotate any secret it
finds; deleting the line is not enough because the value remains in git
history. Semgrep and CodeQL upload SARIF results to the Security tab.

Dependabot (`.github/dependabot.yml`) opens grouped weekly pull requests
for Python packages and GitHub Actions.

### Run the checks locally

```bash
pip install -r requirements-dev.txt
pre-commit install
pre-commit run --all-files
pip-audit -r requirements.txt -r requirements-dev.txt
pip install semgrep==1.185.0
semgrep scan --config p/python --config p/owasp-top-ten \
  --config .semgrep/rules.yml --severity=ERROR --error .
```

The Gitleaks pre-commit hook needs a Gitleaks binary on `PATH`; see
[SECURITY.md](SECURITY.md) for installation and the suppression policy.

### Repository settings

These controls are configured in GitHub, not in this repository:

- Require the `CI`, `Security`, and `CodeQL` checks before merging.
- Enable secret scanning and push protection.
- Disable CodeQL default setup before using the custom `codeql.yml`
  workflow; default and advanced setups cannot analyze the same language.

## Production roadmap

- Add an approve/reject workflow, persistence, and an audit trail for
  dashboard recommendations.
- Add dashboard authentication and role-based access.
- Convert day-based transfers into units and add transport/cost models.
- Add safety stock and configurable service levels.
- Add authentication, rate limiting, and CORS for the API.
- Add structured logging, metrics, and request IDs.
- Add a container image and deployment workflow.
- Add browser-level dashboard tests for filters, exports, and the
  explanation panel.
- Validate recommendations against historical outcomes.
