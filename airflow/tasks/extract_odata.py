"""Extract entity sets from the OData source (and any dropped CSV files) into raw storage."""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import date, timedelta
from pathlib import Path

import pandas as pd
import requests

from .common import ENTITIES, INCREMENTAL, EtlSettings, get_watermarks

log = logging.getLogger(__name__)

# CSV drop-zone file name -> (entity set, column mapping to source property names)
CSV_FILES = {
    "products.csv": ("Products", {
        "sku": "Sku", "name": "Name", "category": "Category", "brand": "Brand", "current_price": "CurrentPrice",
        "unit_cost": "UnitCost", "supplier_lead_time_days": "SupplierLeadTimeDays", "min_order_qty": "MinOrderQty",
        "pack_size": "PackSize", "launch_date": "LaunchDate", "is_active": "IsActive"}),
    "sales.csv": ("SalesTransactions", {
        "transaction_id": "TransactionId", "sku": "Sku", "sale_date": "SaleDate", "quantity": "Quantity",
        "unit_price": "UnitPrice", "on_promo": "OnPromo"}),
    "prices.csv": ("PriceHistory", {"sku": "Sku", "date": "PriceDate", "price": "Price", "price_type": "PriceType"}),
    "inventory.csv": ("Inventory", {
        "sku": "Sku", "available_quantity": "AvailableQuantity", "reserved_quantity": "ReservedQuantity",
        "incoming_quantity": "IncomingQuantity", "incoming_expected_date": "IncomingExpectedDate",
        "backordered_quantity": "BackorderedQuantity", "updated_at": "UpdatedAt"}),
}


REQUIRED_CSV_COLUMNS = {
    "products.csv": ["sku", "name", "category", "brand", "current_price"],
    "sales.csv": ["transaction_id", "sku", "sale_date", "quantity", "unit_price"],
    "prices.csv": ["sku", "date", "price", "price_type"],
    "inventory.csv": ["sku", "available_quantity"],
}


class ExtractionError(RuntimeError):
    pass


def _get(http, url: str, params: dict | None, timeout: int, retries: int = 4):
    for attempt in range(retries):
        try:
            r = http.get(url, params=params, timeout=timeout)
            if r.status_code < 500:
                r.raise_for_status()
                return r.json()
            msg = f"HTTP {r.status_code}"
        except requests.RequestException as exc:
            msg = str(exc)
        if attempt == retries - 1:
            raise ExtractionError(f"OData request failed after {retries} attempts: {url} ({msg})")
        time.sleep(2 ** attempt)
    raise AssertionError("unreachable")


def fetch_entity_set(http, base_url: str, entity_set: str, flt: str | None = None, timeout: int = 60) -> list[dict]:
    """Read every page of an entity set, following @odata.nextLink."""
    url = f"{base_url.rstrip('/')}/{entity_set}"
    params: dict | None = {"$filter": flt} if flt else None
    records: list[dict] = []
    while url:
        body = _get(http, url, params, timeout)
        records.extend(body.get("value", []))
        url, params = body.get("@odata.nextLink"), None  # nextLink already carries the query
    return records


def incremental_filter(entity_set: str, watermarks: dict[str, str], overlap_days: int) -> str | None:
    field = INCREMENTAL.get(entity_set)
    if not field or entity_set not in watermarks:
        return None  # full load
    since = date.fromisoformat(watermarks[entity_set]) - timedelta(days=overlap_days)
    return f"{field} ge '{since.isoformat()}'"


def extract_odata(settings: EtlSettings, out_dir: Path, http=None, watermarks: dict | None = None) -> dict:
    http = http or requests.Session()
    if watermarks is None:
        from .common import engine
        watermarks = get_watermarks(engine(settings))
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    summary = {}
    for entity_set in ENTITIES:
        flt = incremental_filter(entity_set, watermarks, settings.overlap_days)
        recs = fetch_entity_set(http, settings.odata_url, entity_set, flt, settings.request_timeout)
        (raw_dir / f"odata_{entity_set}.json").write_text(json.dumps(recs))
        summary[entity_set] = {"records": len(recs), "mode": "incremental" if flt else "full", "filter": flt}
        log.info("Extracted %s: %d records (%s)", entity_set, len(recs), flt or "full load")
    if summary["Products"]["records"] == 0:
        raise ExtractionError("OData source returned no products - refusing to continue with an empty catalog")
    return summary


def extract_csv(settings: EtlSettings, out_dir: Path) -> dict:
    """Pick up CSV files dropped into the incoming folder and archive them after reading."""
    summary = {}
    raw_dir = out_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)
    if not settings.incoming_dir.exists():
        return summary
    archive = settings.incoming_dir / "processed" / out_dir.name
    for fname, (entity_set, mapping) in CSV_FILES.items():
        path = settings.incoming_dir / fname
        if not path.exists():
            continue
        df = pd.read_csv(path, dtype=str, keep_default_na=False)
        missing = [c for c in REQUIRED_CSV_COLUMNS[fname] if c not in df.columns]
        if missing:
            raise ExtractionError(f"{fname} is missing required columns: {missing}")
        df = df.rename(columns=mapping)[[v for k, v in mapping.items() if k in df.columns]]
        recs = df.replace({"": None}).to_dict(orient="records")
        (raw_dir / f"csv_{entity_set}.json").write_text(json.dumps(recs))
        summary[entity_set] = {"records": len(recs), "mode": "csv", "file": fname}
        archive.mkdir(parents=True, exist_ok=True)
        shutil.move(str(path), archive / fname)
        log.info("Extracted %s from %s: %d records", entity_set, fname, len(recs))
    return summary


def read_raw(out_dir: Path) -> dict[str, pd.DataFrame]:
    """Combine OData and CSV raw files per entity set (CSV rows win on key conflicts later)."""
    frames: dict[str, list[pd.DataFrame]] = {e: [] for e in ENTITIES}
    for path in sorted((out_dir / "raw").glob("*.json")):
        source, entity_set = path.stem.split("_", 1)
        df = pd.DataFrame(json.loads(path.read_text()))
        if not df.empty:
            frames[entity_set].append(df.assign(_source=source))
    return {e: (pd.concat(f, ignore_index=True) if f else pd.DataFrame()) for e, f in frames.items()}
