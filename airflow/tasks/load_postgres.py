"""Idempotent load into PostgreSQL: upserts in one transaction, then watermarks + views."""

from __future__ import annotations

import logging

import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .common import upsert

log = logging.getLogger(__name__)

WATERMARK_COLUMNS = {"sales": ("SalesTransactions", "sale_date"), "prices": ("PriceHistory", "price_date"),
                     "snapshots": ("InventorySnapshots", "snapshot_date")}


def _with_product_id(df: pd.DataFrame, ids: dict[str, int]) -> pd.DataFrame:
    out = df.assign(product_id=df["sku"].map(ids)).drop(columns="sku")
    missing = out["product_id"].isna().sum()
    if missing:  # validated earlier, so this would be a bug rather than bad data
        raise RuntimeError(f"{missing} rows reference SKUs that are not in products")
    out["product_id"] = out["product_id"].astype(int)
    return out


def load(eng: Engine, rows: dict[str, pd.DataFrame]) -> dict[str, int]:
    counts: dict[str, int] = {}
    with eng.begin() as conn:
        p = rows["products"].assign(updated_at=pd.Timestamp.now(tz="UTC"))
        counts["products"] = upsert(conn, "products", p, key=["sku"])
        ids = dict(conn.execute(text("SELECT sku, product_id FROM products")).fetchall())

        counts["sales_transactions"] = upsert(
            conn, "sales_transactions", _with_product_id(rows["sales"], ids), key=["transaction_id"])
        counts["price_history"] = upsert(
            conn, "price_history", _with_product_id(rows["prices"], ids), key=["product_id", "price_date"])
        counts["inventory"] = upsert(conn, "inventory", _with_product_id(rows["inventory"], ids), key=["product_id"])
        counts["inventory_snapshots"] = upsert(
            conn, "inventory_snapshots", _with_product_id(rows["snapshots"], ids), key=["product_id", "snapshot_date"])

        for entity, (source_set, col) in WATERMARK_COLUMNS.items():
            if rows[entity].empty:
                continue
            latest = max(rows[entity][col]).isoformat()
            conn.execute(text("""
                INSERT INTO etl_watermarks (entity, last_value) VALUES (:e, :v)
                ON CONFLICT (entity) DO UPDATE
                  SET last_value = GREATEST(etl_watermarks.last_value, EXCLUDED.last_value), updated_at = now()
            """), {"e": source_set, "v": latest})

        conn.execute(text("REFRESH MATERIALIZED VIEW daily_product_sales"))
    log.info("Loaded: %s", counts)
    return counts
