"""Aggregations and KPI calculations for the dashboard."""

from __future__ import annotations

from datetime import date, timedelta

from sqlalchemy.engine import Connection

from ..repositories import inventory_repository, product_repository, sales_repository
from ..repositories.product_repository import ProductFilters
from . import product_service


def _f(v):
    return None if v is None else float(v)


def _change(cur, prev):
    cur, prev = _f(cur) or 0.0, _f(prev) or 0.0
    return None if prev == 0 else round(cur / prev - 1, 4)


def bucket_for(start: date, end: date) -> str:
    days = (end - start).days + 1
    return "day" if days <= 62 else "week" if days <= 370 else "month"


def dashboard(conn: Connection, start: date | None, end: date | None, category: list[str] | None,
              brand: list[str] | None) -> dict:
    rng = sales_repository.data_range(conn)
    if not rng or rng["end"] is None:
        return {"has_data": False, "message": "No sales data has been loaded yet. The retail_etl pipeline loads it "
                                              "on its first run (see Pipeline Status)."}
    end = min(end or rng["end"], rng["end"])
    start = start or end - timedelta(days=29)
    days = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)

    cur = sales_repository.totals(conn, start, end, category, brand)
    prev = sales_repository.totals(conn, prev_start, prev_end, category, brand)
    filters = ProductFilters(category=category, brand=brand)
    overview, _ = product_repository.search(conn, filters, "name", "asc", 10_000, 0)
    low = [r for r in overview if r["stock_status"] in ("low_stock", "out_of_stock")]
    forecast_units = sum(float(r["forecast_demand_30d"] or 0) for r in overview)
    forecast_rev = sum(float(r["forecast_revenue_30d"] or 0) for r in overview)
    last30 = sales_repository.totals(conn, rng["end"] - timedelta(days=29), rng["end"], category, brand)

    bucket = bucket_for(start, end)
    trend = sales_repository.trend(conn, start, end, bucket, category, brand)
    prio_order = {"critical": 0, "high": 1, "medium": 2, "low": 3, None: 4}
    low_sorted = sorted(low, key=lambda r: (prio_order.get(r["reorder_priority"], 4),
                                            r["predicted_stockout_date"] or date.max))
    return {
        "has_data": True,
        "period": {"start": start, "end": end, "days": days, "previous_start": prev_start, "previous_end": prev_end,
                   "data_start": rng["start"], "data_end": rng["end"]},
        "kpis": {
            "revenue": {"value": _f(cur["revenue"]), "previous": _f(prev["revenue"]),
                        "change": _change(cur["revenue"], prev["revenue"])},
            "units": {"value": int(cur["units"]), "previous": int(prev["units"]),
                      "change": _change(cur["units"], prev["units"])},
            "transactions": {"value": int(cur["transactions"]), "previous": int(prev["transactions"]),
                             "change": _change(cur["transactions"], prev["transactions"])},
            "active_products": {"value": sales_repository.active_products(conn, category, brand),
                                "selling": int(cur["selling_products"])},
            "low_stock_skus": {"value": len(low), "out_of_stock": sum(r["stock_status"] == "out_of_stock" for r in low)},
            "forecast_demand_30d": {"value": round(forecast_units, 1), "revenue": round(forecast_rev, 2),
                                    "change_vs_last_30d": _change(forecast_units, last30["units"]),
                                    "available": any(r["forecast_demand_30d"] is not None for r in overview)},
        },
        "trend": {"bucket": bucket, "points": [{"period": t["period"], "revenue": _f(t["revenue"]),
                                                "units": int(t["units"])} for t in trend]},
        "top_products": [{**t, "revenue": _f(t["revenue"]), "units": int(t["units"])}
                         for t in sales_repository.top_products(conn, start, end, 10, "units", category, brand)],
        "categories": [{**c, "revenue": _f(c["revenue"]), "units": int(c["units"])}
                       for c in sales_repository.category_breakdown(conn, start, end, category, brand)],
        "low_stock": [product_service.to_card(r) for r in low_sorted[:8]],
        "reorder_priorities": inventory_repository.priority_counts(conn),
    }
