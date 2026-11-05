"""Forecast runs, portfolio forecast, and asynchronous training jobs."""

from __future__ import annotations

import hmac
from typing import Literal

from fastapi import APIRouter, Depends, Header, Query
from sqlalchemy.engine import Connection

from ..config import get_settings
from ..database import get_db
from ..errors import AppError
from ..schemas.common import ERROR_RESPONSES
from ..schemas.forecasts import TrainingJob, TrainRequest
from ..services import forecast_service

router = APIRouter(prefix="/api/forecasts", tags=["forecasts"], responses=ERROR_RESPONSES)


def require_training_key(x_api_key: str | None = Header(None, description="Training API key")) -> None:
    key = get_settings().train_api_key
    if not key:
        raise AppError(503, "training_disabled", "Training through the API is disabled: TRAIN_API_KEY is not set.")
    if not x_api_key or not hmac.compare_digest(x_api_key, key):
        raise AppError(401, "unauthorized", "A valid X-API-Key header is required to start training.")


@router.post("/train", status_code=202, response_model=TrainingJob, dependencies=[Depends(require_training_key)],
             summary="Start an asynchronous training job (returns immediately with a job id)")
def train(body: TrainRequest, conn: Connection = Depends(get_db)):
    return forecast_service.submit_training(conn, body.requested_by, body.model_dump(exclude={"requested_by"}))


@router.get("/jobs", response_model=list[TrainingJob], summary="Recent training jobs")
def jobs(limit: int = Query(20, ge=1, le=100), conn: Connection = Depends(get_db)):
    return forecast_service.list_jobs(conn, limit)


@router.get("/jobs/{job_id}", response_model=TrainingJob, summary="Training job progress")
def job(job_id: str, conn: Connection = Depends(get_db)):
    return forecast_service.get_job(conn, job_id)


@router.get("/runs", summary="Forecast runs (production and backtest)")
def runs(run_type: Literal["production", "backtest"] | None = None, limit: int = Query(20, ge=1, le=200),
         conn: Connection = Depends(get_db)):
    return forecast_service.list_runs(conn, run_type, limit)


@router.get("/portfolio", summary="Total daily forecast across products for the latest run")
def portfolio(category: list[str] | None = Query(None), conn: Connection = Depends(get_db)):
    return forecast_service.portfolio(conn, category)
