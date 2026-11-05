"""Sales analytics: dashboard KPIs and forecast accuracy."""

from __future__ import annotations

from datetime import date

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Connection

from ..database import get_db
from ..schemas.common import ERROR_RESPONSES
from ..services import analytics_service, forecast_service

router = APIRouter(prefix="/api/analytics", tags=["analytics"], responses=ERROR_RESPONSES)


@router.get("/dashboard", summary="Revenue, sales, stock and forecast KPIs with trends")
def dashboard(start: date | None = None, end: date | None = None, category: list[str] | None = Query(None),
              brand: list[str] | None = Query(None), conn: Connection = Depends(get_db)):
    return analytics_service.dashboard(conn, start, end, category, brand)


@router.get("/accuracy", summary="Forecast accuracy: backtest by model, and earlier forecasts vs. actuals")
def accuracy(sku: str | None = None, category: list[str] | None = Query(None), conn: Connection = Depends(get_db)):
    return forecast_service.accuracy(conn, sku, category)
