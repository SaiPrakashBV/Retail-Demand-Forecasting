"""Forecast runs, forecast rows, accuracy and training job queries."""

from __future__ import annotations

import json

from sqlalchemy import text
from sqlalchemy.engine import Connection
from sqlalchemy.exc import IntegrityError

from .base import fetch_all, fetch_one

RUN_COLUMNS = """run_id, job_id, run_type, model_name, price_model_name, demand_model_version, price_model_version,
                 mlflow_run_id, price_mlflow_run_id, trained_at, data_start_date, cutoff_date, horizon_days,
                 products_forecast, status, metrics"""


def latest_run(conn: Connection) -> dict | None:
    return fetch_one(conn, f"SELECT {RUN_COLUMNS} FROM latest_production_run")


def get_run(conn: Connection, run_id: str) -> dict | None:
    return fetch_one(conn, f"SELECT {RUN_COLUMNS} FROM forecast_runs WHERE run_id = CAST(:r AS uuid)", r=run_id)


def list_runs(conn: Connection, run_type: str | None, limit: int) -> list[dict]:
    return fetch_all(conn, f"""SELECT {RUN_COLUMNS} FROM forecast_runs
        WHERE (CAST(:t AS text) IS NULL OR run_type = :t) ORDER BY trained_at DESC, cutoff_date DESC LIMIT :n""",
                     t=run_type, n=limit)


def product_forecast(conn: Connection, run_id: str, product_id: int) -> list[dict]:
    return fetch_all(conn, """
        SELECT f.forecast_date AS date, f.demand_prediction AS demand, f.demand_lower, f.demand_upper,
               f.price_prediction AS price, f.price_lower, f.price_upper, f.price_status, f.generated_at,
               s.units AS actual_units, s.avg_price AS actual_avg_price, ph.actual_price
        FROM forecasts f
        LEFT JOIN daily_product_sales s ON s.product_id = f.product_id AND s.sale_date = f.forecast_date
        LEFT JOIN price_history ph ON ph.product_id = f.product_id AND ph.price_date = f.forecast_date
        WHERE f.run_id = CAST(:r AS uuid) AND f.product_id = :p
        ORDER BY f.forecast_date""", r=run_id, p=product_id)


def runs_with_actuals(conn: Connection, product_id: int | None = None) -> list[dict]:
    """Runs (backtest or earlier production) whose forecast dates already have actual data."""
    return fetch_all(conn, """
        WITH data_end AS (SELECT max(sale_date) AS d FROM daily_product_sales)
        SELECT r.run_id, r.run_type, r.model_name, r.price_model_name, r.trained_at, r.cutoff_date,
               r.horizon_days, min(f.generated_at) AS generated_at,
               count(*) FILTER (WHERE f.forecast_date <= data_end.d) AS days_with_actuals
        FROM forecast_runs r JOIN forecasts f ON f.run_id = r.run_id, data_end
        WHERE r.status = 'succeeded' AND (CAST(:p AS integer) IS NULL OR f.product_id = :p)
        GROUP BY r.run_id, data_end.d
        HAVING count(*) FILTER (WHERE f.forecast_date <= data_end.d) > 0
        ORDER BY r.cutoff_date DESC""", p=product_id)


def forecast_vs_actual(conn: Connection, run_ids: list[str], product_id: int | None = None,
                       category: list[str] | None = None) -> list[dict]:
    """Per run: demand/price accuracy over the forecast days that already have actuals."""
    return fetch_all(conn, """
        WITH data_end AS (SELECT max(sale_date) AS d FROM daily_product_sales),
        pairs AS (
            SELECT f.run_id, f.product_id, f.forecast_date, f.demand_prediction AS pred, COALESCE(s.units, 0) AS actual,
                   f.price_prediction AS price_pred, ph.actual_price
            FROM forecasts f
            JOIN products p ON p.product_id = f.product_id
            LEFT JOIN daily_product_sales s ON s.product_id = f.product_id AND s.sale_date = f.forecast_date
            LEFT JOIN price_history ph ON ph.product_id = f.product_id AND ph.price_date = f.forecast_date,
            data_end
            WHERE f.run_id = ANY(CAST(:runs AS uuid[])) AND f.forecast_date <= data_end.d
              AND (CAST(:p AS integer) IS NULL OR f.product_id = :p)
              AND (CAST(:cats AS text[]) IS NULL OR lower(p.category) = ANY(CAST(:cats AS text[])))
        )
        SELECT run_id, count(*) AS n_obs, count(DISTINCT product_id) AS products,
               sum(actual) AS actual_units, sum(pred) AS forecast_units,
               avg(abs(pred - actual)) AS mae, sqrt(avg((pred - actual) ^ 2)) AS rmse,
               sum(abs(pred - actual)) / NULLIF(sum(actual), 0) AS wape,
               sum(pred - actual) / NULLIF(sum(actual), 0) AS bias,
               count(price_pred) FILTER (WHERE actual_price IS NOT NULL) AS price_n_obs,
               avg(abs(price_pred - actual_price)) FILTER (WHERE actual_price IS NOT NULL) AS price_mae,
               avg(abs(price_pred - actual_price) / actual_price) FILTER (WHERE actual_price IS NOT NULL) AS price_mape,
               sum(price_pred - actual_price) FILTER (WHERE actual_price IS NOT NULL)
                 / NULLIF(sum(actual_price) FILTER (WHERE actual_price IS NOT NULL AND price_pred IS NOT NULL), 0)
                 AS price_bias
        FROM pairs GROUP BY run_id""", runs=run_ids, p=product_id,
                     cats=[c.lower() for c in category] if category else None)


def backtest_accuracy(conn: Connection, run_id: str, product_id: int | None = None,
                      category: list[str] | None = None) -> list[dict]:
    """Backtest metrics stored at training time, aggregated per target and candidate model."""
    return fetch_all(conn, """
        SELECT a.target, a.model_name, bool_or(a.is_selected) AS is_selected,
               count(DISTINCT a.product_id) AS products, sum(a.n_obs) AS n_obs,
               sum(a.mae * a.n_obs) / NULLIF(sum(a.n_obs), 0) AS mae,
               sqrt(sum(a.rmse ^ 2 * a.n_obs) / NULLIF(sum(a.n_obs), 0)) AS rmse,
               -- volume-weighted WAPE: sum|e| / sum(actual) == sum(wape * actual) / sum(actual)
               sum(a.mae * a.n_obs) / NULLIF(sum(a.mae * a.n_obs / NULLIF(a.wape, 0)), 0) AS wape,
               avg(a.bias) AS bias, avg(a.mape) AS mape
        FROM model_accuracy a JOIN products p ON p.product_id = a.product_id
        WHERE a.run_id = CAST(:r AS uuid) AND (CAST(:p AS integer) IS NULL OR a.product_id = :p)
          AND (CAST(:cats AS text[]) IS NULL OR lower(p.category) = ANY(CAST(:cats AS text[])))
        GROUP BY a.target, a.model_name ORDER BY a.target, a.model_name""", r=run_id, p=product_id,
                     cats=[c.lower() for c in category] if category else None)


def product_accuracy(conn: Connection, run_id: str, target: str) -> list[dict]:
    return fetch_all(conn, """
        SELECT p.sku, p.name, p.category, a.model_name, a.mae, a.rmse, a.wape, a.bias, a.mape, a.n_obs
        FROM model_accuracy a JOIN products p USING (product_id)
        WHERE a.run_id = CAST(:r AS uuid) AND a.target = :t AND a.is_selected
        ORDER BY a.wape NULLS LAST""", r=run_id, t=target)


def portfolio_daily(conn: Connection, run_id: str, category: list[str] | None = None) -> list[dict]:
    return fetch_all(conn, """
        SELECT f.forecast_date AS date, sum(f.demand_prediction) AS demand, sum(f.demand_lower) AS demand_lower,
               sum(f.demand_upper) AS demand_upper,
               sum(f.demand_prediction * COALESCE(f.price_prediction, p.current_price)) AS revenue
        FROM forecasts f JOIN products p USING (product_id)
        WHERE f.run_id = CAST(:r AS uuid)
          AND (CAST(:cats AS text[]) IS NULL OR lower(p.category) = ANY(CAST(:cats AS text[])))
        GROUP BY 1 ORDER BY 1""", r=run_id, cats=[c.lower() for c in category] if category else None)


# ------------------------------------------------------------------ training jobs
JOB_COLUMNS = """job_id, status, requested_by, requested_at, started_at, finished_at, progress, stage, message,
                 error, params, run_id"""


class ActiveJobExists(Exception):
    def __init__(self, job: dict):
        self.job = job


def create_job(conn: Connection, requested_by: str, params: dict) -> dict:
    try:
        with conn.begin_nested():
            return dict(conn.execute(text(f"""
                INSERT INTO forecast_jobs (requested_by, params) VALUES (:by, CAST(:params AS jsonb))
                RETURNING {JOB_COLUMNS}"""), {"by": requested_by, "params": json.dumps(params)}).mappings().one())
    except IntegrityError:
        active = fetch_one(conn, f"SELECT {JOB_COLUMNS} FROM forecast_jobs WHERE status IN ('queued', 'running') "
                                 "ORDER BY requested_at LIMIT 1")
        raise ActiveJobExists(active) from None


def get_job(conn: Connection, job_id: str) -> dict | None:
    return fetch_one(conn, f"SELECT {JOB_COLUMNS} FROM forecast_jobs WHERE job_id = CAST(:j AS uuid)", j=job_id)


def list_jobs(conn: Connection, limit: int) -> list[dict]:
    return fetch_all(conn, f"SELECT {JOB_COLUMNS} FROM forecast_jobs ORDER BY requested_at DESC LIMIT :n", n=limit)
