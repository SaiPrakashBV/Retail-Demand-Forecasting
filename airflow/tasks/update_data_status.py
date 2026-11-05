"""Record ingestion runs, row counts and quarantined records for monitoring."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Engine

from .common import insert_json_rows


def start_run(eng: Engine, pipeline_id: str, dag_id: str, source: str) -> None:
    with eng.begin() as conn:
        conn.execute(text("""
            INSERT INTO data_pipeline_runs (pipeline_id, dag_id, start_time, status, source)
            VALUES (:p, :d, now(), 'running', :s)
            ON CONFLICT (pipeline_id) DO UPDATE
              SET status = 'running', start_time = now(), end_time = NULL, error = NULL
        """), {"p": pipeline_id, "d": dag_id, "s": source})


def record_quarantine(eng: Engine, pipeline_id: str, records: list[dict]) -> None:
    with eng.begin() as conn:
        conn.execute(text("DELETE FROM quarantine_records WHERE pipeline_id = :p"), {"p": pipeline_id})
        insert_json_rows(conn, "quarantine_records",
                         [{"pipeline_id": pipeline_id, **r} for r in records], json_cols={"record"})


def finish_run(eng: Engine, pipeline_id: str, status: str, *, extracted: int = 0, processed: int = 0,
               quarantined: int = 0, details: dict | None = None, error: str | None = None) -> None:
    with eng.begin() as conn:
        conn.execute(text("""
            UPDATE data_pipeline_runs
               SET end_time = now(), status = :st, records_extracted = :e, records_processed = :p,
                   records_quarantined = :q,
                   details = CAST(:det AS jsonb) || details,
                   error = :err
             WHERE pipeline_id = :pid
        """), {"st": status, "e": extracted, "p": processed, "q": quarantined,
               "det": json.dumps(details or {}, default=str), "err": error, "pid": pipeline_id})


def merge_details(eng: Engine, pipeline_id: str, details: dict) -> None:
    with eng.begin() as conn:
        conn.execute(text("UPDATE data_pipeline_runs SET details = details || CAST(:d AS jsonb) WHERE pipeline_id = :p"),
                     {"d": json.dumps(details, default=str), "p": pipeline_id})
