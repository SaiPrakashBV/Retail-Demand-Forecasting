from __future__ import annotations

from datetime import date, datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class TrainRequest(BaseModel):
    requested_by: str = Field("ui", max_length=120)
    reason: str | None = Field(None, max_length=500)
    horizon_days: int = Field(30, ge=7, le=90)
    backtest_folds: int = Field(3, ge=1, le=6)


class TrainingJob(BaseModel):
    job_id: str
    status: Literal["queued", "running", "succeeded", "failed"]
    requested_by: str
    requested_at: datetime
    started_at: datetime | None
    finished_at: datetime | None
    progress: int
    stage: str | None
    message: str | None
    error: str | None
    params: dict[str, Any]
    run_id: str | None


class ForecastPoint(BaseModel):
    date: date
    demand: float
    demand_lower: float | None
    demand_upper: float | None
    price: float | None
    price_lower: float | None
    price_upper: float | None
    price_status: Literal["forecast", "unavailable"]
    actual_units: int | None
    actual_price: float | None


class RunSummary(BaseModel):
    run_id: str
    run_type: str
    status: str
    generated_at: datetime
    cutoff_date: date
    horizon_days: int
    demand_model: str
    demand_model_version: str | None
    price_model: str | None
    price_model_version: str | None
    mlflow_run_id: str | None
    price_mlflow_run_id: str | None
    products_forecast: int | None
    metrics: dict[str, Any]


class ProductForecast(BaseModel):
    sku: str
    name: str
    run: RunSummary
    generated_at: datetime
    summary: dict[str, Any]
    price_forecast: dict[str, Any]
    points: list[ForecastPoint]
