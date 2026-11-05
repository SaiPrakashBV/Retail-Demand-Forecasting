"""FastAPI service exposing the latest forecasts and sales analytics.

The trainer job writes batch outputs to OUTPUT_DIR; this service reads them and
reloads automatically whenever the files change, so a retrain needs no restart.
"""

from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import pandas as pd
from fastapi import FastAPI, HTTPException, Query
from pydantic import BaseModel

from .config import get_settings

settings = get_settings()
app = FastAPI(
    title="Retail Demand Forecasting API",
    version="0.1.0",
    description="30-day per-product demand forecasts (XGBoost, tracked in MLflow) and sales analytics.",
)


class _Cache:
    """Re-read a file only when its modification time changes."""

    def __init__(self):
        self._store: dict[Path, tuple[float, object]] = {}

    def get(self, path: Path, loader):
        if not path.exists():
            raise HTTPException(503, f"{path.name} not available yet - has the trainer job run?")
        mtime = path.stat().st_mtime
        hit = self._store.get(path)
        if hit is None or hit[0] != mtime:
            hit = (mtime, loader(path))
            self._store[path] = hit
        return hit[1]


cache = _Cache()


def _forecast() -> pd.DataFrame:
    return cache.get(settings.forecast_path, lambda p: pd.read_csv(p, parse_dates=["date"]))


def _analytics_csv(name: str) -> pd.DataFrame:
    return cache.get(settings.analytics_dir / f"{name}.csv", pd.read_csv)


def _json(path: Path) -> dict:
    return cache.get(path, lambda p: json.loads(p.read_text()))


def _records(df: pd.DataFrame) -> list[dict]:
    out = df.copy()
    for c in out.select_dtypes(include=["datetime"]).columns:
        out[c] = out[c].dt.date.astype(str)
    return json.loads(out.to_json(orient="records"))


class ForecastPoint(BaseModel):
    date: date
    forecast: float
    lower: float
    upper: float
    price: float
    on_promo: int


class ProductForecast(BaseModel):
    product_id: str
    category: str
    horizon_days: int
    total_forecast: float
    run_id: str
    points: list[ForecastPoint]


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "forecast_ready": settings.forecast_path.exists()}


@app.get("/model")
def model_info() -> dict:
    """MLflow run, registered model version and backtest metrics behind the current forecast."""
    return _json(settings.model_info_path)


@app.get("/products")
def products(category: str | None = None, abc_class: str | None = Query(None, pattern="^[ABCabc]$")) -> list[dict]:
    df = _analytics_csv("products")
    if category:
        df = df[df["category"].str.lower() == category.lower()]
    if abc_class:
        df = df[df["abc_class"] == abc_class.upper()]
    return _records(df[["product_id", "category", "abc_class", "revenue", "units", "avg_daily_units"]])


@app.get("/forecast")
def forecast_summary(category: str | None = None) -> list[dict]:
    """Total forecast units per product over the horizon."""
    fc = _forecast()
    if category:
        fc = fc[fc["category"].str.lower() == category.lower()]
    agg = (fc.groupby(["product_id", "category"])
             .agg(total_forecast=("forecast", "sum"), total_lower=("lower", "sum"),
                  total_upper=("upper", "sum"), avg_daily=("forecast", "mean"),
                  start=("date", "min"), end=("date", "max"))
             .round({"total_forecast": 2, "total_lower": 2, "total_upper": 2, "avg_daily": 2})
             .reset_index())
    return _records(agg)


@app.get("/forecast/{product_id}", response_model=ProductForecast)
def forecast_product(product_id: str) -> ProductForecast:
    fc = _forecast()
    g = fc[fc["product_id"] == product_id]
    if g.empty:
        raise HTTPException(404, f"No forecast for product {product_id!r}")
    return ProductForecast(
        product_id=product_id,
        category=g["category"].iloc[0],
        horizon_days=len(g),
        total_forecast=round(float(g["forecast"].sum()), 2),
        run_id=str(g["run_id"].iloc[0]),
        points=_records(g[["date", "forecast", "lower", "upper", "price", "on_promo"]]),
    )


@app.get("/analytics/summary")
def analytics_summary() -> dict:
    return _json(settings.analytics_dir / "summary.json")


@app.get("/analytics/categories")
def analytics_categories() -> list[dict]:
    return _records(_analytics_csv("categories"))


@app.get("/analytics/top-products")
def analytics_top_products(n: int = Query(10, ge=1, le=500)) -> list[dict]:
    return _records(_analytics_csv("products").head(n))


@app.get("/analytics/promo-lift")
def analytics_promo_lift() -> list[dict]:
    return _records(_analytics_csv("promo_lift"))


@app.get("/analytics/monthly")
def analytics_monthly(category: str | None = None) -> list[dict]:
    df = _analytics_csv("monthly_by_category")
    if category:
        df = df[df["category"].str.lower() == category.lower()]
    return _records(df)
