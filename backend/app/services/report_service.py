"""Downloadable reports (CSV / Excel) with date, category, SKU and sort options."""

from __future__ import annotations

import io
from dataclasses import dataclass
from datetime import date, timedelta

import pandas as pd
from sqlalchemy.engine import Connection

from ..errors import AppError
from ..repositories import sales_repository
from ..repositories.base import fetch_all


@dataclass
class ReportRequest:
    start: date | None = None
    end: date | None = None
    category: list[str] | None = None
    sku: str | None = None
    sort: str | None = None
    descending: bool = True


def _filters(req: ReportRequest) -> tuple[str, dict]:
    sql, params = "", {}
    if req.category:
        sql += " AND lower(p.category) = ANY(:cats)"
        params["cats"] = [c.lower() for c in req.category]
    if req.sku:
        sql += " AND (p.sku ILIKE :sku OR p.name ILIKE :sku)"
        params["sku"] = f"%{req.sku}%"
    return sql, params


def _dates(conn: Connection, req: ReportRequest, default_days: int) -> tuple[date, date]:
    end = req.end or (sales_repository.data_range(conn) or {}).get("end") or date.today()
    return req.start or end - timedelta(days=default_days - 1), end


def sales_trends(conn, req):
    start, end = _dates(conn, req, 90)
    f, p = _filters(req)
    return fetch_all(conn, f"""
        SELECT s.sale_date AS date, p.sku, p.name, p.category, s.units, s.revenue, s.avg_price, s.on_promo
        FROM daily_product_sales s JOIN products p USING (product_id)
        WHERE s.sale_date BETWEEN :s AND :e {f} ORDER BY s.sale_date, p.sku""", s=start, e=end, **p)


def product_prices(conn, req):
    start, end = _dates(conn, req, 90)
    f, p = _filters(req)
    return fetch_all(conn, f"""
        SELECT ph.price_date AS date, p.sku, p.name, p.category, ph.actual_price, ph.price_type,
               p.current_price AS catalog_price
        FROM price_history ph JOIN products p USING (product_id)
        WHERE ph.price_date BETWEEN :s AND :e {f} ORDER BY ph.price_date, p.sku""", s=start, e=end, **p)


def forecast_vs_actual(conn, req):
    f, p = _filters(req)
    rows = fetch_all(conn, f"""
        WITH data_end AS (SELECT max(sale_date) AS d FROM daily_product_sales)
        SELECT r.run_type, r.cutoff_date, f.generated_at, f.forecast_date AS date, p.sku, p.name, p.category,
               f.demand_prediction AS forecast_units, f.demand_lower, f.demand_upper,
               COALESCE(s.units, 0) AS actual_units,
               f.demand_prediction - COALESCE(s.units, 0) AS error_units,
               f.price_prediction AS forecast_price, ph.actual_price
        FROM forecasts f JOIN forecast_runs r USING (run_id) JOIN products p ON p.product_id = f.product_id
        LEFT JOIN daily_product_sales s ON s.product_id = f.product_id AND s.sale_date = f.forecast_date
        LEFT JOIN price_history ph ON ph.product_id = f.product_id AND ph.price_date = f.forecast_date, data_end
        WHERE f.forecast_date <= data_end.d
          AND (CAST(:s AS date) IS NULL OR f.forecast_date >= :s) AND (CAST(:e AS date) IS NULL OR f.forecast_date <= :e)
          {f}
        ORDER BY r.cutoff_date DESC, p.sku, f.forecast_date""", s=req.start, e=req.end, **p)
    return rows


def inventory_levels(conn, req):
    f, p = _filters(req)
    return fetch_all(conn, f"""
        SELECT p.sku, p.name, p.category, p.brand, o.available_quantity, o.reserved_quantity, o.incoming_quantity,
               o.incoming_expected_date, o.backordered_quantity, o.stock_status, o.days_of_cover,
               o.units_30d, o.forecast_demand_30d, o.inventory_updated_at
        FROM product_overview o JOIN products p USING (product_id) WHERE p.is_active {f}
        ORDER BY p.sku""", **p)


def stockout_risk(conn, req):
    f, p = _filters(req)
    return fetch_all(conn, f"""
        SELECT p.sku, p.name, p.category, rr.priority, rr.predicted_stockout_date, rr.days_of_cover,
               rr.available_quantity, rr.incoming_quantity, rr.lead_time_days, rr.reorder_point, rr.explanation
        FROM reorder_recommendations rr JOIN latest_production_run r USING (run_id)
        JOIN products p ON p.product_id = rr.product_id
        WHERE (rr.predicted_stockout_date IS NOT NULL OR rr.priority IN ('critical', 'high')) {f}
        ORDER BY rr.predicted_stockout_date NULLS LAST, p.sku""", **p)


def reorder_recommendations(conn, req):
    f, p = _filters(req)
    return fetch_all(conn, f"""
        SELECT p.sku, p.name, p.category, p.brand, rr.priority, rr.reorder_quantity,
               rr.reorder_quantity * p.unit_cost AS order_value, p.min_order_qty, p.pack_size,
               rr.inventory_position, rr.reorder_point, rr.safety_stock, rr.target_stock, rr.lead_time_days,
               rr.predicted_stockout_date, rr.explanation, rr.generated_at
        FROM reorder_recommendations rr JOIN latest_production_run r USING (run_id)
        JOIN products p ON p.product_id = rr.product_id
        WHERE rr.reorder_quantity > 0 {f}
        ORDER BY CASE rr.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, p.sku""",
                     **p)


REPORTS = {
    "sales-trends": ("Daily sales by product", sales_trends),
    "product-prices": ("Daily selling prices by product", product_prices),
    "forecast-vs-actual": ("Earlier forecasts compared with actual sales and prices", forecast_vs_actual),
    "inventory-levels": ("Current stock levels and cover", inventory_levels),
    "stockout-risk": ("Products at risk of stock-out", stockout_risk),
    "reorder-recommendations": ("Suggested purchase orders", reorder_recommendations),
}


def build(conn: Connection, report: str, req: ReportRequest) -> pd.DataFrame:
    if report not in REPORTS:
        raise AppError(404, "unknown_report", f"Unknown report {report!r}. Available: {', '.join(REPORTS)}")
    df = pd.DataFrame(REPORTS[report][1](conn, req))
    if req.sort and not df.empty:
        if req.sort not in df.columns:
            raise AppError(422, "invalid_sort", f"Cannot sort by {req.sort!r}. Columns: {', '.join(df.columns)}")
        df = df.sort_values(req.sort, ascending=not req.descending, kind="stable")
    return df


def _excel_safe(df: pd.DataFrame) -> pd.DataFrame:
    """Excel cannot store timezone-aware datetimes: convert them to naive UTC."""
    out = df.copy()
    for c in out.columns:
        if isinstance(out[c].dtype, pd.DatetimeTZDtype):
            out[c] = out[c].dt.tz_convert("UTC").dt.tz_localize(None)
        elif out[c].dtype == object and out[c].map(lambda v: getattr(v, "tzinfo", None) is not None).any():
            out[c] = pd.to_datetime(out[c], utc=True).dt.tz_localize(None)
    return out


def to_bytes(df: pd.DataFrame, fmt: str, sheet: str) -> tuple[bytes, str]:
    if fmt != "xlsx":
        return df.to_csv(index=False).encode(), "text/csv"
    out, clean, name = io.BytesIO(), _excel_safe(df), sheet[:31]
    with pd.ExcelWriter(out, engine="openpyxl") as xl:
        clean.to_excel(xl, index=False, sheet_name=name)
        ws = xl.sheets[name]
        for i, col in enumerate(clean.columns, 1):
            longest = max([len(str(col)), *(len(str(v)) for v in clean[col].head(200))])
            ws.column_dimensions[ws.cell(1, i).column_letter].width = min(longest + 2, 60)
    return out.getvalue(), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def available_reports() -> list[dict]:
    return [{"id": k, "title": v[0]} for k, v in REPORTS.items()]

