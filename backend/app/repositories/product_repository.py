"""Product catalog queries over the product_overview view."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy.engine import Connection

from .base import fetch_all, fetch_one

SORT_COLUMNS = {
    "name": "name", "sku": "sku", "price": "current_price", "stock": "available_quantity",
    "forecast_demand": "forecast_demand_30d", "revenue_30d": "revenue_30d", "units_30d": "units_30d",
    "days_of_cover": "days_of_cover",
}


@dataclass
class ProductFilters:
    q: str | None = None
    category: list[str] | None = None
    brand: list[str] | None = None
    min_price: float | None = None
    max_price: float | None = None
    stock_status: list[str] | None = None
    min_forecast: float | None = None
    max_forecast: float | None = None
    active_only: bool = True


def _where(f: ProductFilters) -> tuple[str, dict]:
    clauses, params = [], {}
    if f.active_only:
        clauses.append("is_active")
    if f.q:
        clauses.append("(sku ILIKE :like OR name ILIKE :like OR brand ILIKE :like OR category ILIKE :like "
                       "OR similarity(name, :q) > 0.25)")
        params.update(like=f"%{f.q.strip()}%", q=f.q.strip())
    for name, col in (("category", "category"), ("brand", "brand"), ("stock_status", "stock_status")):
        values = getattr(f, name)
        if values:
            keys = [f"{name}_{i}" for i in range(len(values))]
            clauses.append(f"lower({col}) IN ({', '.join(':' + k for k in keys)})")
            params.update({k: v.lower() for k, v in zip(keys, values, strict=True)})
    for attr, col, op in (("min_price", "current_price", ">="), ("max_price", "current_price", "<="),
                          ("min_forecast", "forecast_demand_30d", ">="), ("max_forecast", "forecast_demand_30d", "<=")):
        v = getattr(f, attr)
        if v is not None:
            clauses.append(f"{col} {op} :{attr}")
            params[attr] = v
    return ("WHERE " + " AND ".join(clauses)) if clauses else "", params


def search(conn: Connection, f: ProductFilters, sort: str, order: str, limit: int, offset: int) -> tuple[list[dict], int]:
    where, params = _where(f)
    direction = "DESC" if order == "desc" else "ASC"
    if sort == "relevance" and f.q:
        order_by = ("(lower(sku) = lower(:q)) DESC, GREATEST(similarity(name, :q), similarity(sku, :q)) DESC, name")
    else:
        col = SORT_COLUMNS.get(sort, "name")
        order_by = f"{col} {direction} NULLS LAST, name"
    items = fetch_all(conn, f"SELECT * FROM product_overview {where} ORDER BY {order_by} LIMIT :limit OFFSET :offset",
                      **params, limit=limit, offset=offset)
    total = fetch_one(conn, f"SELECT count(*) AS n FROM product_overview {where}", **params)["n"]
    return items, total


def get_by_sku(conn: Connection, sku: str) -> dict | None:
    return fetch_one(conn, "SELECT * FROM product_overview WHERE lower(sku) = lower(:sku)", sku=sku)


def filter_options(conn: Connection) -> dict:
    cats = fetch_all(conn, "SELECT category AS value, count(*) AS count FROM products WHERE is_active "
                           "GROUP BY 1 ORDER BY 1")
    brands = fetch_all(conn, "SELECT brand AS value, count(*) AS count FROM products WHERE is_active "
                             "GROUP BY 1 ORDER BY 1")
    rng = fetch_one(conn, "SELECT min(current_price) AS min_price, max(current_price) AS max_price, "
                          "max(forecast_demand_30d) AS max_forecast FROM product_overview WHERE is_active")
    status = fetch_all(conn, "SELECT stock_status AS value, count(*) AS count FROM product_overview "
                             "WHERE is_active GROUP BY 1 ORDER BY 1")
    return {"categories": cats, "brands": brands, "stock_statuses": status, **rng}
