from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

StockStatus = Literal["in_stock", "low_stock", "out_of_stock"]


class ProductCard(BaseModel):
    sku: str
    name: str
    category: str
    brand: str
    current_price: float
    forecast_price: float | None
    forecast_price_change: float | None
    price_forecast_available: bool
    available_quantity: int
    reserved_quantity: int
    incoming_quantity: int
    stock_status: StockStatus
    stock_status_label: str
    forecast_demand_30d: float | None
    units_30d: int
    revenue_30d: float | None
    days_of_cover: float | None
    reorder_priority: str | None
    reorder_quantity: int | None


class ProductPage(BaseModel):
    items: list[ProductCard]
    total: int
    page: int
    page_size: int
    pages: int


class FacetValue(BaseModel):
    value: str
    count: int


class FilterOptions(BaseModel):
    categories: list[FacetValue]
    brands: list[FacetValue]
    stock_statuses: list[FacetValue]
    min_price: float | None
    max_price: float | None
    max_forecast: float | None


class PriceAvailability(BaseModel):
    available: bool
    reason: str | None
    history_days: int


class ProductDetail(ProductCard):
    unit_cost: float | None
    launch_date: date | None
    is_active: bool
    supplier_lead_time_days: int
    min_order_qty: int
    pack_size: int
    incoming_expected_date: date | None
    inventory_updated_at: datetime | None
    forecast_generated_at: datetime | None
    price_forecast: PriceAvailability
    reorder: dict | None
    data_end_date: date | None
