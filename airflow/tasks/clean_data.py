"""Standardise raw records: column names, types, trimming, exact-duplicate removal.

Values that cannot be parsed become NaN/NaT here and are rejected by validation, which
quarantines the *original* record (kept in the ``_raw`` column).
"""

from __future__ import annotations

import pandas as pd

COLUMNS = {
    "products": {"Sku": "sku", "Name": "name", "Category": "category", "Brand": "brand",
                 "CurrentPrice": "current_price", "UnitCost": "unit_cost",
                 "SupplierLeadTimeDays": "supplier_lead_time_days", "MinOrderQty": "min_order_qty",
                 "PackSize": "pack_size", "LaunchDate": "launch_date", "IsActive": "is_active",
                 "ModifiedAt": "source_modified_at"},
    "sales": {"TransactionId": "transaction_id", "Sku": "sku", "SaleDate": "sale_date", "Quantity": "quantity",
              "UnitPrice": "unit_price", "OnPromo": "on_promo"},
    "prices": {"Sku": "sku", "PriceDate": "price_date", "Price": "actual_price", "PriceType": "price_type"},
    "inventory": {"Sku": "sku", "AvailableQuantity": "available_quantity", "ReservedQuantity": "reserved_quantity",
                  "IncomingQuantity": "incoming_quantity", "IncomingExpectedDate": "incoming_expected_date",
                  "BackorderedQuantity": "backordered_quantity", "UpdatedAt": "updated_at"},
    "snapshots": {"Sku": "sku", "SnapshotDate": "snapshot_date", "Quantity": "quantity"},
}
SOURCE_SET = {"products": "Products", "sales": "SalesTransactions", "prices": "PriceHistory",
              "inventory": "Inventory", "snapshots": "InventorySnapshots"}
DATE_COLS = {"launch_date", "sale_date", "price_date", "snapshot_date", "incoming_expected_date"}
TIMESTAMP_COLS = {"source_modified_at", "updated_at"}
NUMERIC_COLS = {"current_price", "unit_cost", "unit_price", "actual_price"}
INT_COLS = {"supplier_lead_time_days", "min_order_qty", "pack_size", "quantity", "available_quantity",
            "reserved_quantity", "incoming_quantity", "backordered_quantity"}
BOOL_COLS = {"is_active", "on_promo"}
TRUE = {"true", "1", "yes", "y", "t"}


def _missing(v) -> bool:
    return v is None or (not isinstance(v, (str, bool)) and pd.isna(v))


def _clean_str(v):
    if _missing(v):
        return None
    v = str(v).strip()
    return v or None


def _to_bool(s: pd.Series) -> pd.Series:
    return s.astype(object).map(lambda v: None if _missing(v) else (v if isinstance(v, bool) else str(v).strip().lower() in TRUE))


def clean_entity(entity: str, raw: pd.DataFrame) -> tuple[pd.DataFrame, int]:
    """Return (clean frame with a ``_raw`` column, number of exact duplicates dropped)."""
    mapping = COLUMNS[entity]
    if raw.empty:
        return pd.DataFrame(columns=[*mapping.values(), "_source", "_raw"]), 0
    df = raw.copy()
    for col in mapping:
        if col not in df.columns:
            df[col] = None
    before = len(df)
    df = df.drop_duplicates(subset=list(mapping)).reset_index(drop=True)
    dropped = before - len(df)

    df["_raw"] = df[list(mapping)].astype(object).where(df[list(mapping)].notna(), None).to_dict(orient="records")
    df = df.rename(columns=mapping)[[*mapping.values(), "_source", "_raw"]]

    for c in df.columns:
        if c.startswith("_"):
            continue
        if c in DATE_COLS:
            df[c] = pd.to_datetime(df[c], errors="coerce", format="mixed").dt.date
        elif c in TIMESTAMP_COLS:
            df[c] = pd.to_datetime(df[c], errors="coerce", utc=True, format="mixed")
        elif c in NUMERIC_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce").round(2)
        elif c in INT_COLS:
            df[c] = pd.to_numeric(df[c], errors="coerce")
        elif c in BOOL_COLS:
            df[c] = _to_bool(df[c])
        else:
            df[c] = df[c].astype(object).map(_clean_str)

    if "sku" in df:
        df["sku"] = df["sku"].map(lambda v: v.upper() if isinstance(v, str) else None)
    if entity == "products":
        df["brand"] = df["brand"].fillna("Unbranded")
        df["is_active"] = df["is_active"].fillna(True)
        df["supplier_lead_time_days"] = df["supplier_lead_time_days"].fillna(7)
        df["min_order_qty"] = df["min_order_qty"].fillna(1)
        df["pack_size"] = df["pack_size"].fillna(1)
    if entity == "sales":
        df["on_promo"] = df["on_promo"].fillna(False)
    if entity == "prices":
        df["price_type"] = df["price_type"].map(lambda v: v.lower() if isinstance(v, str) else None)
    if entity == "inventory":
        for c in ("reserved_quantity", "incoming_quantity", "backordered_quantity"):
            df[c] = df[c].fillna(0)
        df["updated_at"] = df["updated_at"].fillna(pd.Timestamp.now(tz="UTC"))
    return df, dropped


def clean_all(raw: dict[str, pd.DataFrame]) -> tuple[dict[str, pd.DataFrame], dict[str, int]]:
    frames, dupes = {}, {}
    for entity, source in SOURCE_SET.items():
        frames[entity], dupes[entity] = clean_entity(entity, raw.get(source, pd.DataFrame()))
    return frames, dupes
