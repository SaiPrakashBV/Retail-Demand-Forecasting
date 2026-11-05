"""Forecast retrieval, forecast-vs-actual comparison and training job coordination."""

from __future__ import annotations

from sqlalchemy.engine import Connection

from ..errors import AppError, NotFound, Unavailable
from ..repositories import forecast_repository as repo
from . import product_service


def _f(v):
    return None if v is None else float(v)


def _require_run(conn: Connection, run_id: str | None) -> dict:
    run = repo.get_run(conn, run_id) if run_id else repo.latest_run(conn)
    if run is None:
        if run_id:
            raise NotFound(f"Forecast run {run_id} not found.", run_id=run_id)
        raise Unavailable("No forecast has been generated yet. The forecast-training workflow runs after the first "
                          "data load; you can also start it from the Forecasts page.", code="forecast_unavailable")
    return run


def run_summary(run: dict) -> dict:
    return {
        "run_id": str(run["run_id"]), "run_type": run["run_type"], "status": run["status"],
        "generated_at": run["trained_at"], "cutoff_date": run["cutoff_date"], "horizon_days": run["horizon_days"],
        "demand_model": run["model_name"], "demand_model_version": run["demand_model_version"],
        "price_model": run["price_model_name"], "price_model_version": run["price_model_version"],
        "mlflow_run_id": run["mlflow_run_id"], "price_mlflow_run_id": run["price_mlflow_run_id"],
        "products_forecast": run["products_forecast"], "metrics": run["metrics"],
    }


def product_forecast(conn: Connection, sku: str, run_id: str | None = None) -> dict:
    product = product_service.require_product(conn, sku)
    run = _require_run(conn, run_id)
    points = repo.product_forecast(conn, str(run["run_id"]), product["product_id"])
    if not points:
        raise Unavailable(
            f"{product['sku']} has no forecast in this run: it does not have enough sales history yet "
            "(new or recently launched product).", code="forecast_unavailable", sku=product["sku"])
    out = [{
        "date": p["date"], "demand": _f(p["demand"]), "demand_lower": _f(p["demand_lower"]),
        "demand_upper": _f(p["demand_upper"]), "price": _f(p["price"]), "price_lower": _f(p["price_lower"]),
        "price_upper": _f(p["price_upper"]), "price_status": p["price_status"],
        "actual_units": p["actual_units"], "actual_price": _f(p["actual_price"]),
    } for p in points]
    price_ok = any(p["price_status"] == "forecast" for p in out)
    current = _f(product["current_price"])
    end_price = out[-1]["price"] if price_ok else None
    return {
        "sku": product["sku"], "name": product["name"], "run": run_summary(run),
        "generated_at": points[0]["generated_at"],
        "summary": {
            "total_demand": round(sum(p["demand"] for p in out), 2),
            "total_demand_lower": round(sum(p["demand_lower"] or 0 for p in out), 2),
            "total_demand_upper": round(sum(p["demand_upper"] or 0 for p in out), 2),
            "avg_daily_demand": round(sum(p["demand"] for p in out) / len(out), 2),
            "current_price": current, "forecast_price_end": end_price,
            "forecast_price_change": (end_price / current - 1) if (end_price and current) else None,
            "price_forecast_available": price_ok,
        },
        "price_forecast": product_service.price_availability(conn, product["product_id"], price_ok),
        "points": out,
    }


def comparison(conn: Connection, sku: str, run_id: str | None = None) -> dict:
    """Earlier predictions vs. what actually happened, for one product."""
    product = product_service.require_product(conn, sku)
    runs = repo.runs_with_actuals(conn, product["product_id"])
    if not runs:
        raise Unavailable("No earlier forecasts overlap with actual sales yet. Backtest forecasts appear after the "
                          "first training run; production forecasts are compared once their dates have passed.",
                          code="comparison_unavailable")
    selected = next((r for r in runs if str(r["run_id"]) == run_id), runs[0]) if run_id else runs[0]
    points = [p for p in repo.product_forecast(conn, str(selected["run_id"]), product["product_id"])]
    metrics = {str(m["run_id"]): m for m in repo.forecast_vs_actual(conn, [str(r["run_id"]) for r in runs],
                                                                     product["product_id"])}
    return {
        "sku": product["sku"],
        "runs": [{**{k: (str(v) if k == "run_id" else v) for k, v in r.items()},
                  "metrics": _metric_view(metrics.get(str(r["run_id"])))} for r in runs],
        "selected_run_id": str(selected["run_id"]),
        "points": [{"date": p["date"], "forecast": _f(p["demand"]), "lower": _f(p["demand_lower"]),
                    "upper": _f(p["demand_upper"]), "actual": p["actual_units"],
                    "forecast_price": _f(p["price"]), "actual_price": _f(p["actual_price"])} for p in points],
    }


def _metric_view(m: dict | None) -> dict | None:
    if not m:
        return None
    keys = ("n_obs", "products", "actual_units", "forecast_units", "mae", "rmse", "wape", "bias",
            "price_n_obs", "price_mae", "price_mape", "price_bias")
    return {k: _f(m.get(k)) for k in keys}


def accuracy(conn: Connection, sku: str | None, category: list[str] | None) -> dict:
    """Backtest accuracy by model (from training) + live forecast-vs-actual by run."""
    run = _require_run(conn, None)
    product_id = product_service.require_product(conn, sku)["product_id"] if sku else None
    backtest = repo.backtest_accuracy(conn, str(run["run_id"]), product_id, category)
    runs = repo.runs_with_actuals(conn, product_id)
    live = {str(m["run_id"]): m for m in repo.forecast_vs_actual(conn, [str(r["run_id"]) for r in runs],
                                                                  product_id, category)}
    by_target: dict[str, list] = {"demand": [], "price": []}
    for b in backtest:
        by_target[b["target"]].append(b)  # Decimals/dates are serialised by FastAPI
    return {
        "run": run_summary(run),
        "backtest": by_target,
        "forecast_vs_actual": [{"run_id": str(r["run_id"]), "run_type": r["run_type"], "cutoff_date": r["cutoff_date"],
                                "generated_at": r["generated_at"], "demand_model": r["model_name"],
                                "price_model": r["price_model_name"],
                                "metrics": _metric_view(live.get(str(r["run_id"])))} for r in runs],
        "products": {t: [{**p, **{k: _f(p[k]) for k in ("mae", "rmse", "wape", "bias", "mape")}}
                         for p in repo.product_accuracy(conn, str(run["run_id"]), t)] for t in ("demand", "price")}
        if not sku else None,
    }


def portfolio(conn: Connection, category: list[str] | None) -> dict:
    run = _require_run(conn, None)
    daily = repo.portfolio_daily(conn, str(run["run_id"]), category)
    return {"run": run_summary(run),
            "daily": [{k: (_f(v) if k != "date" else v) for k, v in d.items()} for d in daily],
            "total_demand": round(sum(float(d["demand"]) for d in daily), 2),
            "total_revenue": round(sum(float(d["revenue"]) for d in daily), 2)}


def list_runs(conn: Connection, run_type: str | None, limit: int) -> list[dict]:
    return [run_summary(r) for r in repo.list_runs(conn, run_type, limit)]


# ------------------------------------------------------------------ training jobs
def job_view(job: dict) -> dict:
    return {**job, "job_id": str(job["job_id"]), "run_id": str(job["run_id"]) if job["run_id"] else None}


def submit_training(conn: Connection, requested_by: str, params: dict) -> dict:
    try:
        return job_view(repo.create_job(conn, requested_by, params))
    except repo.ActiveJobExists as exc:
        job = job_view(exc.job) if exc.job else None
        raise AppError(409, "job_already_active",
                       "A training job is already queued or running; wait for it to finish.",
                       {"job_id": job["job_id"] if job else None, "status": job["status"] if job else None}) from None


def get_job(conn: Connection, job_id: str) -> dict:
    job = repo.get_job(conn, job_id)
    if job is None:
        raise NotFound(f"Training job {job_id} not found.", job_id=job_id)
    return job_view(job)


def list_jobs(conn: Connection, limit: int) -> list[dict]:
    return [job_view(j) for j in repo.list_jobs(conn, limit)]
