"""Application configuration from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache


def _list(name: str, default: str) -> list[str]:
    return [v.strip() for v in os.environ.get(name, default).split(",") if v.strip()]


@dataclass(frozen=True)
class Settings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "DATABASE_URL", "postgresql+psycopg2://retail:retail@localhost:5432/retail"))
    # Required for POST /api/forecasts/train. Empty = training via the API is disabled.
    train_api_key: str = field(default_factory=lambda: os.environ.get("TRAIN_API_KEY", ""))
    cors_origins: list[str] = field(default_factory=lambda: _list("CORS_ORIGINS", "http://localhost:3000,http://localhost:5173"))
    mlflow_ui_url: str = field(default_factory=lambda: os.environ.get("MLFLOW_UI_URL", "http://localhost:5000"))
    airflow_ui_url: str = field(default_factory=lambda: os.environ.get("AIRFLOW_UI_URL", "http://localhost:8080"))
    # Data older than this many hours (vs. the latest sales date) is flagged as stale.
    stale_after_hours: int = field(default_factory=lambda: int(os.environ.get("DATA_STALE_AFTER_HOURS", "48")))
    # Reorder planning
    review_period_days: int = field(default_factory=lambda: int(os.environ.get("REORDER_REVIEW_PERIOD_DAYS", "7")))
    service_level: float = field(default_factory=lambda: float(os.environ.get("REORDER_SERVICE_LEVEL", "0.95")))


@lru_cache
def get_settings() -> Settings:
    return Settings()
