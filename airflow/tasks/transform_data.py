"""Shape validated records into the rows each PostgreSQL table expects."""

from __future__ import annotations

import pandas as pd

TABLE_COLUMNS = {
    "products": ["sku", "name", "category", "brand", "current_price", "unit_cost", "supplier_lead_time_days",
                 "min_order_qty", "pack_size", "launch_date", "is_active", "source_modified_at"],
    "sales": ["transaction_id", "sku", "sale_date", "quantity", "unit_price", "on_promo"],
    "prices": ["sku", "price_date", "actual_price", "price_type"],
    "inventory": ["sku", "available_quantity", "reserved_quantity", "incoming_quantity", "incoming_expected_date",
                  "backordered_quantity", "updated_at"],
    "snapshots": ["sku", "snapshot_date", "quantity"],
}
INT_COLUMNS = {"supplier_lead_time_days", "min_order_qty", "pack_size", "quantity", "available_quantity",
               "reserved_quantity", "incoming_quantity", "backordered_quantity"}


def _source_priority(df: pd.DataFrame, key: list[str]) -> pd.DataFrame:
    """When OData and a CSV drop both supply a key, the CSV (manual correction) wins."""
    if "_source" not in df or df.empty:
        return df
    order = df["_source"].map({"odata": 0, "csv": 1}).fillna(0)
    return df.assign(_o=order).sort_values("_o", kind="stable").drop_duplicates(key, keep="last").drop(columns="_o")


def transform(valid: dict[str, pd.DataFrame]) -> dict[str, pd.DataFrame]:
    keys = {"products": ["sku"], "sales": ["transaction_id"], "prices": ["sku", "price_date"],
            "inventory": ["sku"], "snapshots": ["sku", "snapshot_date"]}
    out = {}
    for entity, cols in TABLE_COLUMNS.items():
        df = _source_priority(valid[entity], keys[entity])[cols].copy()
        for c in cols:
            if c in INT_COLUMNS:
                df[c] = df[c].astype("Int64")
        if entity == "products":
            df["name"] = df["name"].str.replace(r"\s+", " ", regex=True)
            df["category"] = df["category"].str.title()
        out[entity] = df.reset_index(drop=True)
    return out
