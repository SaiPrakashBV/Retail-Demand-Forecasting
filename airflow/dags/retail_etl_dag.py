"""Daily retail ingestion: OData (+ CSV drop-zone) -> clean -> validate -> transform -> PostgreSQL.

A critical data-quality failure fails the ``validate`` task without retries, so nothing is
loaded and forecasting is not triggered. Quarantined records are visible in the app's
Pipeline Status page and in the ``quarantine_records`` table.
"""

from __future__ import annotations

from datetime import timedelta

import pendulum
from airflow.exceptions import AirflowFailException
from airflow.providers.standard.operators.trigger_dagrun import TriggerDagRunOperator
from airflow.sdk import dag, get_current_context, task


def _mark_failed(context) -> None:
    from tasks.pipeline import step_fail

    ti = context["ti"]
    step_fail(context["run_id"], f"Task '{ti.task_id}' failed: {context.get('exception')}")


@dag(
    dag_id="retail_etl",
    description="Extract retail data from OData/CSV, validate it and load PostgreSQL",
    schedule="0 1 * * *",  # daily at 01:00 UTC
    start_date=pendulum.datetime(2026, 1, 1, tz="UTC"),
    catchup=False,
    max_active_runs=1,
    default_args={"retries": 2, "retry_delay": timedelta(minutes=1), "on_failure_callback": _mark_failed},
    tags=["retail", "etl"],
    doc_md=__doc__,
)
def retail_etl():
    @task
    def start() -> str:
        from tasks.pipeline import step_start

        ctx = get_current_context()
        return step_start(ctx["run_id"], ctx["dag"].dag_id)

    @task
    def extract(work: str) -> dict:
        from tasks.pipeline import step_extract

        return step_extract(work, get_current_context()["run_id"])

    @task
    def clean(work: str) -> dict:
        from tasks.pipeline import step_clean

        return step_clean(work, get_current_context()["run_id"])

    @task
    def validate(work: str, clean_paths: dict, summary: dict) -> dict:
        from tasks.pipeline import step_validate
        from tasks.validate_data import CriticalDataQualityError

        try:
            return step_validate(work, get_current_context()["run_id"], clean_paths, summary)
        except CriticalDataQualityError as exc:
            raise AirflowFailException(str(exc)) from exc  # bad data: retrying will not help

    @task
    def transform(work: str, valid_paths: dict) -> dict:
        from tasks.pipeline import step_transform

        return step_transform(work, valid_paths)

    @task
    def load(rows_paths: dict) -> dict:
        from tasks.pipeline import step_load

        return step_load(get_current_context()["run_id"], rows_paths)

    @task
    def update_status(_loaded: dict) -> dict:
        from tasks.pipeline import step_finish

        return step_finish(get_current_context()["run_id"])

    work = start()
    summary = extract(work)
    cleaned = clean(work)
    summary >> cleaned
    valid = validate(work, cleaned, summary)
    rows = transform(work, valid)
    status = update_status(load(rows))

    status >> TriggerDagRunOperator(
        task_id="trigger_forecast_training",
        trigger_dag_id="forecast_training",
        conf={"reason": "new data loaded by retail_etl"},
        wait_for_completion=False,
    )


retail_etl()
