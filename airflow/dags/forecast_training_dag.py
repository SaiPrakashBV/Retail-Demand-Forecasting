"""Forecast training: submit an asynchronous training job to the API and wait for it.

Training runs in the ``forecast-worker`` service, not in Airflow: this DAG only asks the
API for a job (``POST /api/forecasts/train``) and polls ``GET /api/forecasts/jobs/{id}``.
Triggered by ``retail_etl`` after each successful load, or manually from the Airflow UI.
"""

from __future__ import annotations

import os
from datetime import timedelta

import pendulum
import requests
from airflow.sdk import dag, get_current_context, task
from airflow.sdk.bases.sensor import PokeReturnValue
from airflow.sdk.exceptions import AirflowFailException

API_URL = os.environ.get("RETAIL_API_URL", "http://api:8000").rstrip("/")


def _headers() -> dict:
    return {"X-API-Key": os.environ.get("TRAIN_API_KEY", "")}


@dag(
    dag_id="forecast_training",
    description="Train demand and price models and publish 30-day forecasts",
    schedule=None,
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 1, "retry_delay": timedelta(minutes=2)},
    tags=["retail", "ml"],
    doc_md=__doc__,
)
def forecast_training():
    @task
    def submit_job() -> str:
        ctx = get_current_context()
        reason = (ctx["dag_run"].conf or {}).get("reason", "manual trigger")
        r = requests.post(f"{API_URL}/api/forecasts/train", headers=_headers(),
                          json={"requested_by": f"airflow:{ctx['run_id']}", "reason": reason}, timeout=30)
        if r.status_code == 409:  # a job is already queued/running: follow that one
            return r.json()["error"]["details"]["job_id"]
        if r.status_code in (401, 403):
            raise AirflowFailException(f"API rejected the training request ({r.status_code}): check TRAIN_API_KEY")
        r.raise_for_status()
        return r.json()["job_id"]

    @task.sensor(poke_interval=30, timeout=3 * 3600, mode="reschedule")
    def wait_for_job(job_id: str) -> PokeReturnValue:
        r = requests.get(f"{API_URL}/api/forecasts/jobs/{job_id}", timeout=30)
        r.raise_for_status()
        job = r.json()
        if job["status"] == "failed":
            raise AirflowFailException(f"Training job {job_id} failed: {job.get('error')}")
        return PokeReturnValue(is_done=job["status"] == "succeeded", xcom_value=job)

    wait_for_job(submit_job())


forecast_training()
