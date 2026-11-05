"""Runtime configuration, read from environment variables with sensible defaults."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


def _env(name: str, default: str) -> str:
    return os.environ.get(name, default)


@dataclass(frozen=True)
class Settings:
    # Paths
    data_path: Path = field(default_factory=lambda: Path(_env("DATA_PATH", "data/sales.csv")))
    output_dir: Path = field(default_factory=lambda: Path(_env("OUTPUT_DIR", "outputs")))

    # Forecasting
    horizon: int = field(default_factory=lambda: int(_env("FORECAST_HORIZON", "30")))
    backtest_folds: int = field(default_factory=lambda: int(_env("BACKTEST_FOLDS", "3")))

    # Synthetic data (used only when DATA_PATH does not exist)
    synthetic_products: int = field(default_factory=lambda: int(_env("SYNTHETIC_PRODUCTS", "40")))
    synthetic_start: str = field(default_factory=lambda: _env("SYNTHETIC_START", "2023-11-01"))
    synthetic_end: str = field(default_factory=lambda: _env("SYNTHETIC_END", "2026-10-31"))
    seed: int = field(default_factory=lambda: int(_env("SEED", "42")))

    # MLflow
    tracking_uri: str = field(default_factory=lambda: _env("MLFLOW_TRACKING_URI", "sqlite:///mlflow.db"))
    experiment: str = field(default_factory=lambda: _env("MLFLOW_EXPERIMENT", "retail-demand-forecast"))
    registered_model: str = field(default_factory=lambda: _env("MLFLOW_REGISTERED_MODEL", "retail-demand-xgb"))

    @property
    def forecast_path(self) -> Path:
        return self.output_dir / "forecast.csv"

    @property
    def analytics_dir(self) -> Path:
        return self.output_dir / "analytics"

    @property
    def model_info_path(self) -> Path:
        return self.output_dir / "model_info.json"


def get_settings() -> Settings:
    return Settings()
