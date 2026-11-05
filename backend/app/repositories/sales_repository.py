"""Historical sales, prices and aggregate analytics queries."""

from __future__ import annotations

from datetime import date

from sqlalchemy.engine import Connection

from .base import fetch_all, fetch_one, scalar


def data_range(conn: Connection) -> dict:
    return fetch_one(conn, "SELECT min(sale_date) AS start, max(sale_date) AS end FROM daily_product_sales")


def daily_sales(conn: Connection, product_id: int, start: date, end: date) -> list[dict]:
    """Every calendar day in range (zero-filled), with the in-stock flag from snapshots."""
    return fetch_all(conn, """
        SELECT d::date AS date,
               COALESCE(s.units, 0) AS units, COALESCE(s.revenue, 0) AS revenue, s.avg_price,
               COALESCE(s.on_promo, FALSE) AS on_promo,
               snap.quantity AS stock_on_hand,
               CASE WHEN snap.quantity IS NULL THEN NULL ELSE snap.quantity > 0 END AS in_stock
        FROM generate_series(CAST(:start AS date), CAST(:end AS date), interval '1 day') d
        LEFT JOIN daily_product_sales s ON s.product_id = :pid AND s.sale_date = d::date
        LEFT JOIN inventory_snapshots snap ON snap.product_id = :pid AND snap.snapshot_date = d::date
        ORDER BY 1""", pid=product_id, start=start, end=end)


def price_history(conn: Connection, product_id: int, start: date | None = None, end: date | None = None) -> list[dict]:
    return fetch_all(conn, """
        SELECT price_date AS date, actual_price, price_type FROM price_history
        WHERE product_id = :pid AND (CAST(:start AS date) IS NULL OR price_date >= :start)
          AND (CAST(:end AS date) IS NULL OR price_date <= :end)
        ORDER BY price_date""", pid=product_id, start=start, end=end)


def price_history_stats(conn: Connection, product_id: int) -> dict:
    return fetch_one(conn, """
        SELECT count(*) AS n, min(price_date) AS first_date, max(price_date) AS last_date,
               count(DISTINCT actual_price) AS distinct_prices
        FROM price_history WHERE product_id = :pid""", pid=product_id)


def _filters(category: list[str] | None, brand: list[str] | None, alias: str = "p") -> tuple[str, dict]:
    sql, params = "", {}
    if category:
        sql += f" AND lower({alias}.category) = ANY(:cats)"
        params["cats"] = [c.lower() for c in category]
    if brand:
        sql += f" AND lower({alias}.brand) = ANY(:brands)"
        params["brands"] = [b.lower() for b in brand]
    return sql, params


def totals(conn: Connection, start: date, end: date, category=None, brand=None) -> dict:
    f, params = _filters(category, brand)
    return fetch_one(conn, f"""
        SELECT COALESCE(sum(s.revenue), 0) AS revenue, COALESCE(sum(s.units), 0) AS units,
               COALESCE(sum(s.transactions), 0) AS transactions, count(DISTINCT s.product_id) AS selling_products
        FROM daily_product_sales s JOIN products p USING (product_id)
        WHERE s.sale_date BETWEEN :start AND :end {f}""", start=start, end=end, **params)


def trend(conn: Connection, start: date, end: date, bucket: str, category=None, brand=None) -> list[dict]:
    assert bucket in ("day", "week", "month")
    f, params = _filters(category, brand)
    return fetch_all(conn, f"""
        SELECT date_trunc('{bucket}', s.sale_date)::date AS period,
               sum(s.revenue) AS revenue, sum(s.units) AS units
        FROM daily_product_sales s JOIN products p USING (product_id)
        WHERE s.sale_date BETWEEN :start AND :end {f}
        GROUP BY 1 ORDER BY 1""", start=start, end=end, **params)


def top_products(conn: Connection, start: date, end: date, limit: int, by: str, category=None, brand=None) -> list[dict]:
    f, params = _filters(category, brand)
    col = "units" if by == "units" else "revenue"
    return fetch_all(conn, f"""
        SELECT p.sku, p.name, p.category, p.brand, sum(s.units) AS units, sum(s.revenue) AS revenue
        FROM daily_product_sales s JOIN products p USING (product_id)
        WHERE s.sale_date BETWEEN :start AND :end {f}
        GROUP BY p.sku, p.name, p.category, p.brand
        ORDER BY {col} DESC LIMIT :limit""", start=start, end=end, limit=limit, **params)


def category_breakdown(conn: Connection, start: date, end: date, category=None, brand=None) -> list[dict]:
    f, params = _filters(category, brand)
    return fetch_all(conn, f"""
        SELECT p.category, sum(s.revenue) AS revenue, sum(s.units) AS units, count(DISTINCT p.product_id) AS products
        FROM daily_product_sales s JOIN products p USING (product_id)
        WHERE s.sale_date BETWEEN :start AND :end {f}
        GROUP BY p.category ORDER BY revenue DESC""", start=start, end=end, **params)


def active_products(conn: Connection, category=None, brand=None) -> int:
    f, params = _filters(category, brand)
    return scalar(conn, f"SELECT count(*) FROM products p WHERE p.is_active {f}", **params)
