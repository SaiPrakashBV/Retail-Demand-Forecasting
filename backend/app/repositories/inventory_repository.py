"""Inventory, snapshots and reorder recommendation queries."""

from __future__ import annotations

from datetime import date

from sqlalchemy.engine import Connection

from .base import fetch_all, fetch_one


def snapshots(conn: Connection, product_id: int, start: date, end: date) -> list[dict]:
    return fetch_all(conn, """
        SELECT snapshot_date AS date, quantity FROM inventory_snapshots
        WHERE product_id = :p AND snapshot_date BETWEEN :s AND :e ORDER BY snapshot_date""", p=product_id, s=start, e=end)


def recommendation(conn: Connection, product_id: int) -> dict | None:
    return fetch_one(conn, """
        SELECT rr.* FROM reorder_recommendations rr JOIN latest_production_run r USING (run_id)
        WHERE rr.product_id = :p""", p=product_id)


def reorders(conn: Connection, priority: list[str] | None, category: list[str] | None, q: str | None,
             actionable_only: bool, sort: str, limit: int, offset: int) -> tuple[list[dict], int]:
    where = ["TRUE"]
    params: dict = {"limit": limit, "offset": offset}
    if priority:
        where.append("rr.priority = ANY(:prio)")
        params["prio"] = [p.lower() for p in priority]
    if category:
        where.append("lower(p.category) = ANY(:cats)")
        params["cats"] = [c.lower() for c in category]
    if q:
        where.append("(p.sku ILIKE :like OR p.name ILIKE :like)")
        params["like"] = f"%{q}%"
    if actionable_only:
        where.append("rr.reorder_quantity > 0")
    order = {
        "priority": "CASE rr.priority WHEN 'critical' THEN 0 WHEN 'high' THEN 1 WHEN 'medium' THEN 2 ELSE 3 END, "
                    "rr.predicted_stockout_date NULLS LAST, rr.days_of_cover NULLS LAST",
        "stockout_date": "rr.predicted_stockout_date NULLS LAST",
        "reorder_quantity": "rr.reorder_quantity DESC",
        "days_of_cover": "rr.days_of_cover NULLS LAST",
    }.get(sort, "rr.priority")
    base = f"""FROM reorder_recommendations rr JOIN latest_production_run r USING (run_id)
               JOIN products p ON p.product_id = rr.product_id WHERE {' AND '.join(where)}"""
    items = fetch_all(conn, f"""SELECT p.sku, p.name, p.category, p.brand, p.current_price, p.unit_cost,
                                       p.min_order_qty, p.pack_size, rr.* {base}
                                ORDER BY {order}, p.sku LIMIT :limit OFFSET :offset""", **params)
    total = fetch_one(conn, f"SELECT count(*) AS n {base}", **params)["n"]
    return items, total


def priority_counts(conn: Connection) -> dict[str, int]:
    rows = fetch_all(conn, """SELECT priority, count(*) AS n FROM reorder_recommendations rr
                              JOIN latest_production_run r USING (run_id)
                              WHERE rr.reorder_quantity > 0 GROUP BY 1""")
    return {r["priority"]: r["n"] for r in rows}
