# AI Health Supply Chain Decision Support

A small, deterministic decision-support service for synthetic health
supply-chain inventory risk and redistribution analysis. It identifies
stockout and expiry risk, proposes redistribution candidates, and can
optionally ask Gemini to explain the results in plain language.

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
- Optionally produces a constrained LLM explanation of the summary.

## Project structure

```text
data/facilities.csv     Synthetic facility inventory dataset
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

Open <http://127.0.0.1:8000/docs> for the interactive OpenAPI docs.

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
- A "Generate explanation" panel with loading, error (`503`), and
  guardrail-warning states.
- Light/dark themes, responsive layouts, keyboard focus styles, and
  print styles.

The dashboard calls `/summary`, `/inventory`, `/recommendations`, and
`/explanation`; it never recalculates risk itself.

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
| `GET` | `/explanation?refresh=false` | LLM explanation of the summary |

Filters are case-insensitive and optional.

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

## Data dictionary

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

Validation rejects missing columns, non-numeric values, missing or blank
fields, negative values, zero consumption, zero lead time, and duplicate
facility/medicine rows.

## Governance and limitations

- Synthetic data only; no real patient information.
- The deterministic layers make the classifications; the LLM only
  explains them.
- The LLM receives a constrained prompt and its output is checked for
  CRITICAL/HIGH reporting and a human-review statement. Warnings are
  returned in `governance.guardrail_warnings`.
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
python -m pytest --cov=src
```

Tests cover validation, risk boundaries, allocation limits, decision
summary structure, prompt/guardrail behavior, provider caching and
errors, and API status mapping.

## Production roadmap

- Convert day-based transfers into units and add transport/cost models.
- Add safety stock and configurable service levels.
- Add authentication, rate limiting, and CORS.
- Add structured logging, metrics, and request IDs.
- Add a container image and deployment workflow.
- Validate recommendations against historical outcomes.
