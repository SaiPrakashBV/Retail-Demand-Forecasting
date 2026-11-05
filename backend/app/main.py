"""FastAPI application initialisation."""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text

from .config import get_settings
from .database import get_engine
from .errors import install_error_handlers
from .routes import forecasts, inventory, pipelines, products, reports, sales

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

app = FastAPI(
    title="Retail Sales Analytics & Forecasting API",
    version="2.0.0",
    description="Product search, sales analytics, 30-day demand and price forecasts, inventory recommendations, "
                "reports and pipeline status.",
)
app.add_middleware(CORSMiddleware, allow_origins=get_settings().cors_origins, allow_methods=["*"],
                   allow_headers=["*"])
install_error_handlers(app)
for module in (products, sales, forecasts, inventory, reports, pipelines):
    app.include_router(module.router)


@app.get("/health", tags=["health"])
def health() -> dict:
    """Liveness plus a database check (the app stays up when the database is down)."""
    try:
        with get_engine().connect() as conn:
            conn.execute(text("SELECT 1"))
        db = "ok"
    except Exception as exc:  # noqa: BLE001
        db = f"unavailable: {type(exc).__name__}"
    return {"status": "ok", "database": db}
