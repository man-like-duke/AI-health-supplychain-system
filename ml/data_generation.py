"""Generate a reproducible synthetic history for stockout prediction.

The generator starts from the project's existing synthetic facility
snapshot. For every facility/medicine pair it simulates monthly
observations and then simulates the next 30 days to produce the target.

Why the target is not leaked
----------------------------
Features are drawn from the *current* observation only: stock on hand,
observed demand, lead time, recent trend, prior stockout count, and
replenishment cadence. The label comes from a separate forward simulation
that draws future demand and future replenishment arrivals from the same
random generator. Those future draws are never written to a feature column,
so the model cannot read the answer from its inputs.

The data is synthetic. Any metrics derived from it describe this simulation,
not real-world health supply chains.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd

from ml.schema import HISTORY_COLUMNS, TARGET_COLUMN
from src.config import DAYS_PER_MONTH
from src.data import load_facility_data
from src.errors import DataValidationError

DEFAULT_HISTORY_PATH = (
    Path(__file__).resolve().parent.parent
    / "data"
    / "synthetic_stockout_history.csv"
)

DEFAULT_SEED = 42
PERIODS_PER_PAIR = 12
PREDICTION_WINDOW_DAYS = 30

BASE_COLUMNS = {
    "facility",
    "region",
    "medicine",
    "current_stock",
    "monthly_consumption",
    "lead_time_days",
    "expiry_days",
}


@dataclass(frozen=True)
class GenerationConfig:
    """Parameters that control the synthetic simulation."""

    seed: int = DEFAULT_SEED
    periods_per_pair: int = PERIODS_PER_PAIR
    prediction_window_days: int = PREDICTION_WINDOW_DAYS


def _clip(value: float, low: float, high: float) -> float:
    return float(min(high, max(low, value)))


def _simulate_window(
    rng: np.random.Generator,
    *,
    starting_stock: float,
    daily_demand_mean: float,
    replenishment_frequency: float,
    window_days: int,
) -> int:
    """Simulate a forward window and return 1 if stock ever reaches zero.

    Replenishment is stochastic: orders arrive at a cadence derived from
    the observed frequency, order sizes vary, and a small share of pairs
    experience a supply disruption for the whole window. These hidden
    draws are what make the label non-deterministic.
    """
    stock = starting_stock
    daily_arrival_probability = min(
        1.0, max(0.0, replenishment_frequency) / window_days
    )
    order_size = daily_demand_mean * (
        DAYS_PER_MONTH / max(replenishment_frequency, 1.0)
    )
    supply_disruption = rng.random() < 0.12

    for _ in range(window_days):
        demand = daily_demand_mean * float(rng.lognormal(mean=0.0, sigma=0.35))
        stock -= demand

        if stock <= 0:
            return 1

        if not supply_disruption and rng.random() < daily_arrival_probability:
            stock += order_size * float(rng.lognormal(mean=0.0, sigma=0.25))

    return 0


def generate_stockout_history(
    base: pd.DataFrame | None = None,
    config: GenerationConfig | None = None,
) -> pd.DataFrame:
    """Return a deterministic synthetic history for the given seed.

    Passing ``base`` is useful in tests. When omitted, the project's
    validated facility dataset is loaded.
    """
    config = config or GenerationConfig()
    frame = load_facility_data() if base is None else base.copy()

    missing = BASE_COLUMNS - set(frame.columns)
    if missing:
        raise DataValidationError(
            f"Missing required columns: {sorted(missing)}"
        )

    if frame.empty:
        raise DataValidationError("The base dataset is empty.")

    if config.periods_per_pair < 1:
        raise DataValidationError("periods_per_pair must be at least 1.")

    if config.prediction_window_days < 1:
        raise DataValidationError("prediction_window_days must be at least 1.")

    rng = np.random.default_rng(config.seed)
    rows: list[dict] = []

    for record in frame.itertuples(index=False):
        base_daily = float(record.monthly_consumption) / DAYS_PER_MONTH
        base_days_of_stock = float(record.current_stock) / base_daily

        seasonal_amplitude = float(rng.uniform(0.08, 0.22))
        seasonal_phase = float(rng.uniform(0.0, 2.0 * np.pi))
        trend_slope = float(rng.normal(0.0, 0.08))
        start_month = int(rng.integers(1, 13))
        previous_daily = base_daily

        # Prior stockout history is correlated with the snapshot's cover,
        # but it is still a pre-window observation.
        history_rate = _clip(
            6.0 * float(np.exp(-base_days_of_stock / 45.0)),
            0.0,
            6.0,
        )

        for period in range(config.periods_per_pair):
            month = ((start_month - 1 + period) % 12) + 1

            seasonal = 1.0 + seasonal_amplitude * float(
                np.sin(2.0 * np.pi * (month - 1) / 12.0 + seasonal_phase)
            )
            trend = 1.0 + trend_slope * (
                period / max(config.periods_per_pair - 1, 1) - 0.5
            )
            demand_noise = _clip(
                float(rng.lognormal(mean=0.0, sigma=0.28)),
                0.45,
                2.5,
            )
            observed_daily = base_daily * seasonal * trend * demand_noise
            observed_monthly = observed_daily * DAYS_PER_MONTH

            recent_trend = (
                _clip(observed_daily / previous_daily, 0.5, 2.0)
                if previous_daily > 0
                else 1.0
            )
            previous_daily = observed_daily

            stock_cycle = _clip(
                float(rng.lognormal(mean=0.0, sigma=0.45)),
                0.2,
                2.4,
            )
            current_stock = float(record.current_stock) * stock_cycle

            lead_time = _clip(
                float(record.lead_time_days)
                * float(rng.lognormal(mean=0.0, sigma=0.15)),
                1.0,
                90.0,
            )
            expiry = _clip(
                float(record.expiry_days) * float(rng.uniform(0.5, 1.4)),
                5.0,
                365.0,
            )
            replenishment = _clip(
                (DAYS_PER_MONTH / lead_time)
                * float(rng.lognormal(mean=0.0, sigma=0.3)),
                0.25,
                8.0,
            )
            historical_stockouts = int(
                _clip(float(rng.poisson(history_rate)), 0.0, 12.0)
            )

            target = _simulate_window(
                rng,
                starting_stock=current_stock,
                daily_demand_mean=observed_daily,
                replenishment_frequency=replenishment,
                window_days=config.prediction_window_days,
            )

            rows.append(
                {
                    "facility": str(record.facility),
                    "region": str(record.region),
                    "medicine": str(record.medicine),
                    "month": month,
                    "current_stock": round(current_stock, 1),
                    "monthly_consumption": round(observed_monthly, 1),
                    "recent_consumption_trend": round(recent_trend, 3),
                    "lead_time_days": round(lead_time, 1),
                    "historical_stockout_count": historical_stockouts,
                    "replenishment_frequency": round(replenishment, 2),
                    "expiry_days": round(expiry, 1),
                    "avg_daily_consumption": round(observed_daily, 2),
                    "days_of_stock": round(current_stock / observed_daily, 1),
                    TARGET_COLUMN: target,
                }
            )

    return pd.DataFrame(rows, columns=list(HISTORY_COLUMNS))


def write_stockout_history(
    output_path: Path = DEFAULT_HISTORY_PATH,
    base: pd.DataFrame | None = None,
    config: GenerationConfig | None = None,
) -> pd.DataFrame:
    """Generate the history and write it to ``output_path``."""
    history = generate_stockout_history(base=base, config=config)
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    history.to_csv(output_path, index=False)
    return history


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Generate the synthetic stockout history dataset.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_HISTORY_PATH,
        help=(
            "Destination CSV "
            "(defaults to data/synthetic_stockout_history.csv)."
        ),
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=DEFAULT_SEED,
        help="Random seed for the simulation.",
    )
    parser.add_argument(
        "--periods",
        type=int,
        default=PERIODS_PER_PAIR,
        help="Monthly observations per facility/medicine pair.",
    )
    args = parser.parse_args(argv)

    history = write_stockout_history(
        output_path=args.output,
        config=GenerationConfig(
            seed=args.seed,
            periods_per_pair=args.periods,
        ),
    )

    positives = int(history[TARGET_COLUMN].sum())
    share = positives / len(history) if len(history) else 0.0
    print(
        f"Wrote {len(history)} rows to {args.output} "
        f"({positives} positive, {share:.1%})."
    )
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
