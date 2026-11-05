"""ML configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class MlSettings:
    database_url: str = field(default_factory=lambda: _env(
        "DATABASE_URL", "postgresql+psycopg2://retail:retail@localhost:5432/retail"))
    tracking_uri: str = field(default_factory=lambda: _env("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
    demand_experiment: str = field(default_factory=lambda: _env("MLFLOW_DEMAND_EXPERIMENT", "retail-demand-forecast"))
    price_experiment: str = field(default_factory=lambda: _env("MLFLOW_PRICE_EXPERIMENT", "retail-price-forecast"))
    demand_model_name: str = field(default_factory=lambda: _env("MLFLOW_DEMAND_MODEL", "retail-demand-model"))
    price_model_name: str = field(default_factory=lambda: _env("MLFLOW_PRICE_MODEL", "retail-price-model"))
    horizon: int = field(default_factory=lambda: int(_env("FORECAST_HORIZON", "30")))
    backtest_folds: int = field(default_factory=lambda: int(_env("BACKTEST_FOLDS", "3")))
    # Products need this much sales history (days since first sale) to get a demand forecast.
    min_demand_history_days: int = field(default_factory=lambda: int(_env("MIN_DEMAND_HISTORY_DAYS", "90")))
    # ...and this many days of recorded prices to get a price forecast.
    min_price_history_days: int = field(default_factory=lambda: int(_env("PRICE_MIN_HISTORY_DAYS", "180")))
    demand_candidates: tuple[str, ...] = field(default_factory=lambda: tuple(
        c.strip() for c in _env("DEMAND_MODELS", "xgboost,prophet").split(",") if c.strip()))
    n_jobs: int = field(default_factory=lambda: int(_env("ML_N_JOBS", str(max(os.cpu_count() or 2, 2)))))
    seed: int = field(default_factory=lambda: int(_env("SEED", "42")))
