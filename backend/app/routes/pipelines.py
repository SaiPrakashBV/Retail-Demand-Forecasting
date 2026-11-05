"""Data freshness, ingestion runs and forecast job status."""

from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Connection

from ..config import get_settings
from ..database import get_db
from ..errors import NotFound
from ..repositories import forecast_repository, pipeline_repository, sales_repository
from ..schemas.common import ERROR_RESPONSES
from ..services.forecast_service import job_view, run_summary

router = APIRouter(prefix="/api/pipelines", tags=["pipelines"], responses=ERROR_RESPONSES)


@router.get("/status", summary="Ingestion and forecasting status, with data freshness")
def status(limit: int = Query(15, ge=1, le=100), conn: Connection = Depends(get_db)):
    s = get_settings()
    runs = pipeline_repository.recent_runs(conn, limit)
    last_ok = pipeline_repository.last_successful_run(conn)
    rng = sales_repository.data_range(conn) or {}
    latest_run = forecast_repository.latest_run(conn)
    now = datetime.now(timezone.utc)
    data_end = rng.get("end")
    lag_hours = None
    if data_end:
        end_of_day = datetime.combine(data_end, datetime.max.time(), tzinfo=timezone.utc)
        lag_hours = round(max((now - end_of_day).total_seconds(), 0) / 3600, 1)
    latest_quarantine = (pipeline_repository.quarantine_summary(conn, runs[0]["pipeline_id"]) if runs else [])
    return {
        "freshness": {
            "data_start": rng.get("start"), "data_end": data_end, "hours_since_data_end": lag_hours,
            "is_stale": lag_hours is None or lag_hours > s.stale_after_hours,
            "stale_after_hours": s.stale_after_hours,
            "last_successful_ingestion": last_ok["end_time"] if last_ok else None,
            "latest_forecast_at": latest_run["trained_at"] if latest_run else None,
            "latest_forecast_cutoff": latest_run["cutoff_date"] if latest_run else None,
        },
        "ingestion_runs": runs,
        "latest_quarantine": latest_quarantine,
        "forecast_jobs": [job_view(j) for j in forecast_repository.list_jobs(conn, 10)],
        "latest_forecast_run": run_summary(latest_run) if latest_run else None,
        "table_counts": pipeline_repository.table_counts(conn),
        "links": {"airflow": s.airflow_ui_url, "mlflow": s.mlflow_ui_url},
    }


@router.get("/runs/{pipeline_id}", summary="One ingestion run with validation details")
def run(pipeline_id: str, conn: Connection = Depends(get_db)):
    row = pipeline_repository.run_details(conn, pipeline_id)
    if not row:
        raise NotFound(f"Pipeline run {pipeline_id!r} not found.")
    return {**row, "quarantine_summary": pipeline_repository.quarantine_summary(conn, pipeline_id)}


@router.get("/runs/{pipeline_id}/quarantine", summary="Quarantined records of an ingestion run")
def quarantine(pipeline_id: str, limit: int = Query(100, ge=1, le=1000), conn: Connection = Depends(get_db)):
    return pipeline_repository.quarantine(conn, pipeline_id, limit)
