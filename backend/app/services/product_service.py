"""Product search, filtering, details, sales and price history."""

from __future__ import annotations

import os
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.engine import Connection

from ..errors import NotFound
from ..repositories import inventory_repository, product_repository, sales_repository
from ..repositories.product_repository import ProductFilters

PRICE_MIN_HISTORY_DAYS = int(os.environ.get("PRICE_MIN_HISTORY_DAYS", "180"))
STOCK_LABELS = {"in_stock": "In stock", "low_stock": "Low stock", "out_of_stock": "Out of stock"}


def _f(v):
    return None if v is None else float(v)


def to_card(row: dict) -> dict:
    price, fc_price = _f(row["current_price"]), _f(row["forecast_price_end"])
    return {
        "sku": row["sku"], "name": row["name"], "category": row["category"], "brand": row["brand"],
        "current_price": price,
        "forecast_price": fc_price if row["price_forecast_available"] else None,
        "forecast_price_change": (fc_price / price - 1) if (fc_price and price and row["price_forecast_available"]) else None,
        "price_forecast_available": bool(row["price_forecast_available"]),
        "available_quantity": row["available_quantity"], "reserved_quantity": row["reserved_quantity"],
        "incoming_quantity": row["incoming_quantity"],
        "stock_status": row["stock_status"], "stock_status_label": STOCK_LABELS[row["stock_status"]],
        "forecast_demand_30d": _f(row["forecast_demand_30d"]),
        "units_30d": int(row["units_30d"]), "revenue_30d": _f(row["revenue_30d"]),
        "days_of_cover": _f(row["days_of_cover"]), "reorder_priority": row["reorder_priority"],
        "reorder_quantity": row["reorder_quantity"],
    }


def search_products(conn: Connection, filters: ProductFilters, sort: str, order: str, page: int, page_size: int) -> dict:
    items, total = product_repository.search(conn, filters, sort, order, page_size, (page - 1) * page_size)
    return {"items": [to_card(r) for r in items], "total": total, "page": page, "page_size": page_size,
            "pages": max(1, -(-total // page_size))}


def require_product(conn: Connection, sku: str) -> dict:
    row = product_repository.get_by_sku(conn, sku)
    if row is None:
        raise NotFound(f"No product with SKU {sku!r}. Check the SKU or search the catalog by name.", sku=sku)
    return row


def price_availability(conn: Connection, product_id: int, has_price_forecast: bool) -> dict:
    stats = sales_repository.price_history_stats(conn, product_id)
    n = stats["n"]
    if has_price_forecast:
        return {"available": True, "reason": None, "history_days": n}
    if n == 0:
        reason = ("The data source has no price history for this product, only its catalog price. "
                  "Future prices are unavailable until price-history records exist.")
    elif n < PRICE_MIN_HISTORY_DAYS:
        reason = (f"Only {n} days of price history; at least {PRICE_MIN_HISTORY_DAYS} are needed "
                  "for a price forecast.")
    else:
        reason = "No price forecast has been generated yet. Run forecast training to create one."
    return {"available": False, "reason": reason, "history_days": n}


def product_detail(conn: Connection, sku: str) -> dict:
    row = require_product(conn, sku)
    card = to_card(row)
    rec = inventory_repository.recommendation(conn, row["product_id"])
    rng = sales_repository.data_range(conn)
    return {
        **card,
        "unit_cost": _f(row["unit_cost"]), "launch_date": row["launch_date"], "is_active": row["is_active"],
        "supplier_lead_time_days": row["supplier_lead_time_days"], "min_order_qty": row["min_order_qty"],
        "pack_size": row["pack_size"], "incoming_expected_date": row["incoming_expected_date"],
        "inventory_updated_at": row["inventory_updated_at"],
        "forecast_generated_at": row["forecast_generated_at"],
        "price_forecast": price_availability(conn, row["product_id"], bool(row["price_forecast_available"])),
        "reorder": rec,
        "data_end_date": rng["end"] if rng else None,
    }


def _window(conn: Connection, start: date | None, end: date | None, default_days: int) -> tuple[date, date]:
    rng = sales_repository.data_range(conn)
    last = (rng or {}).get("end") or date.today()
    end = end or last
    start = start or end - timedelta(days=default_days - 1)
    if start > end:
        start, end = end, start
    return start, end


def sales_history(conn: Connection, sku: str, start: date | None, end: date | None, granularity: str) -> dict:
    row = require_product(conn, sku)
    start, end = _window(conn, start, end, 180)
    daily = sales_repository.daily_sales(conn, row["product_id"], start, end)
    if granularity != "day" and daily:
        df = pd.DataFrame(daily)
        df["date"] = pd.to_datetime(df["date"])
        rule = {"week": "W-MON", "month": "MS"}[granularity]
        g = df.set_index("date").resample(rule, label="left", closed="left")
        agg = pd.DataFrame({"units": g["units"].sum(), "revenue": g["revenue"].sum(),
                            "on_promo": g["on_promo"].any(), "stockout_days": g["in_stock"].apply(lambda s: int((s == False).sum()))})  # noqa: E712
        agg["avg_price"] = (agg["revenue"].astype(float) / agg["units"].replace(0, pd.NA)).round(2)
        daily = [{"date": d.date(), **{k: (None if pd.isna(v) else v) for k, v in r.items()}}
                 for d, r in agg.iterrows()]
    totals = {"units": int(sum(d["units"] for d in daily)), "revenue": float(sum(float(d["revenue"]) for d in daily))}
    return {"sku": row["sku"], "start": start, "end": end, "granularity": granularity, "points": daily, "totals": totals}


def price_history(conn: Connection, sku: str, start: date | None, end: date | None) -> dict:
    row = require_product(conn, sku)
    start, end = _window(conn, start, end, 365)
    points = sales_repository.price_history(conn, row["product_id"], start, end)
    availability = price_availability(conn, row["product_id"], bool(row["price_forecast_available"]))
    return {"sku": row["sku"], "start": start, "end": end, "current_price": _f(row["current_price"]),
            "points": points, "has_history": availability["history_days"] > 0, "forecast": availability}


def product_inventory(conn: Connection, sku: str, days: int) -> dict:
    row = require_product(conn, sku)
    end = sales_repository.data_range(conn)["end"] or date.today()
    return {
        "sku": row["sku"], "available_quantity": row["available_quantity"],
        "reserved_quantity": row["reserved_quantity"], "incoming_quantity": row["incoming_quantity"],
        "incoming_expected_date": row["incoming_expected_date"], "backordered_quantity": row["backordered_quantity"],
        "updated_at": row["inventory_updated_at"], "stock_status": row["stock_status"],
        "stock_status_label": STOCK_LABELS[row["stock_status"]],
        "supplier_lead_time_days": row["supplier_lead_time_days"], "min_order_qty": row["min_order_qty"],
        "pack_size": row["pack_size"],
        "recommendation": inventory_repository.recommendation(conn, row["product_id"]),
        "snapshots": inventory_repository.snapshots(conn, row["product_id"], end - timedelta(days=days - 1), end),
    }
