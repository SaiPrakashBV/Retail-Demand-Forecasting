"""Data pipeline run and quarantine queries."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from .base import fetch_all, fetch_one


def recent_runs(conn: Connection, limit: int) -> list[dict]:
    return fetch_all(conn, """
        SELECT pipeline_id, dag_id, start_time, end_time, status, source, records_extracted, records_processed,
               records_quarantined, error, details -> 'critical' AS critical,
               EXTRACT(EPOCH FROM (end_time - start_time)) AS duration_seconds
        FROM data_pipeline_runs ORDER BY start_time DESC LIMIT :n""", n=limit)


def last_successful_run(conn: Connection) -> dict | None:
    return fetch_one(conn, """SELECT pipeline_id, end_time FROM data_pipeline_runs WHERE status = 'succeeded'
                              ORDER BY end_time DESC LIMIT 1""")


def run_details(conn: Connection, pipeline_id: str) -> dict | None:
    return fetch_one(conn, "SELECT * FROM data_pipeline_runs WHERE pipeline_id = :p", p=pipeline_id)


def quarantine(conn: Connection, pipeline_id: str, limit: int) -> list[dict]:
    return fetch_all(conn, """SELECT quarantine_id, entity, reason, record, quarantined_at FROM quarantine_records
                              WHERE pipeline_id = :p ORDER BY quarantine_id LIMIT :n""", p=pipeline_id, n=limit)


def quarantine_summary(conn: Connection, pipeline_id: str) -> list[dict]:
    return fetch_all(conn, """SELECT entity, reason, count(*) AS count FROM quarantine_records
                              WHERE pipeline_id = :p GROUP BY 1, 2 ORDER BY 3 DESC""", p=pipeline_id)


def table_counts(conn: Connection) -> dict:
    return fetch_one(conn, """SELECT (SELECT count(*) FROM products) AS products,
        (SELECT count(*) FROM sales_transactions) AS sales_transactions,
        (SELECT count(*) FROM price_history) AS price_history,
        (SELECT count(*) FROM inventory_snapshots) AS inventory_snapshots,
        (SELECT count(*) FROM forecasts) AS forecasts""")
