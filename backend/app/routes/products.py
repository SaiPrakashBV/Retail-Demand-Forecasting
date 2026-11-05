"""Product listing, searching and details (with sales, prices, forecast and inventory)."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Connection

from ..database import get_db
from ..repositories.product_repository import ProductFilters
from ..schemas.common import ERROR_RESPONSES
from ..schemas.forecasts import ProductForecast
from ..schemas.products import FilterOptions, ProductDetail, ProductPage
from ..services import forecast_service, product_service

router = APIRouter(prefix="/api/products", tags=["products"], responses=ERROR_RESPONSES)


@router.get("", response_model=ProductPage, summary="Search and filter the product catalog")
def list_products(
    q: str | None = Query(None, description="Matches SKU, name, brand or category (fuzzy on name)"),
    category: list[str] | None = Query(None), brand: list[str] | None = Query(None),
    min_price: float | None = Query(None, ge=0), max_price: float | None = Query(None, ge=0),
    stock_status: list[Literal["in_stock", "low_stock", "out_of_stock"]] | None = Query(None),
    min_forecast: float | None = Query(None, ge=0, description="Minimum forecast units over 30 days"),
    max_forecast: float | None = Query(None, ge=0),
    sort: Literal["relevance", "name", "sku", "price", "stock", "forecast_demand", "revenue_30d", "units_30d",
                  "days_of_cover"] = "relevance",
    order: Literal["asc", "desc"] = "asc",
    page: int = Query(1, ge=1), page_size: int = Query(24, ge=1, le=200),
    conn: Connection = Depends(get_db),
):
    filters = ProductFilters(q=q, category=category, brand=brand, min_price=min_price, max_price=max_price,
                             stock_status=stock_status, min_forecast=min_forecast, max_forecast=max_forecast)
    return product_service.search_products(conn, filters, sort if q or sort != "relevance" else "name", order,
                                           page, page_size)


@router.get("/filters", response_model=FilterOptions, summary="Available filter values")
def filter_options(conn: Connection = Depends(get_db)):
    from ..repositories.product_repository import filter_options as fo

    return fo(conn)


@router.get("/{sku}", response_model=ProductDetail, summary="Single product details")
def get_product(sku: str, conn: Connection = Depends(get_db)):
    return product_service.product_detail(conn, sku)


@router.get("/{sku}/sales", summary="Historical sales (zero-filled), daily/weekly/monthly")
def product_sales(sku: str, start: date | None = None, end: date | None = None,
                  granularity: Literal["day", "week", "month"] = "day", conn: Connection = Depends(get_db)):
    return product_service.sales_history(conn, sku, start, end, granularity)


@router.get("/{sku}/prices", summary="Historical selling prices")
def product_prices(sku: str, start: date | None = None, end: date | None = None, conn: Connection = Depends(get_db)):
    return product_service.price_history(conn, sku, start, end)


@router.get("/{sku}/forecast", response_model=ProductForecast, summary="30-day demand and price forecast")
def product_forecast(sku: str, run_id: str | None = None, conn: Connection = Depends(get_db)):
    return forecast_service.product_forecast(conn, sku, run_id)


@router.get("/{sku}/forecast-comparison", summary="Earlier forecasts vs. actual sales")
def product_forecast_comparison(sku: str, run_id: str | None = None, conn: Connection = Depends(get_db)):
    return forecast_service.comparison(conn, sku, run_id)


@router.get("/{sku}/inventory", summary="Stock information and reorder recommendation")
def product_inventory(sku: str, days: int = Query(90, ge=7, le=730), conn: Connection = Depends(get_db)):
    return product_service.product_inventory(conn, sku, days)
