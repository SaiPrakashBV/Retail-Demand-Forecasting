"""Shared settings and database helpers for the ETL tasks (framework-agnostic)."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import pandas as pd
from psycopg2.extras import Json, execute_values
from sqlalchemy import create_engine, text
from sqlalchemy.engine import Engine

# Source entity set -> internal entity name
ENTITIES = {
    "Products": "products",
    "SalesTransactions": "sales",
    "PriceHistory": "prices",
    "Inventory": "inventory",
    "InventorySnapshots": "snapshots",
}
# Entities extracted incrementally, and the date property their watermark tracks.
INCREMENTAL = {"SalesTransactions": "SaleDate", "PriceHistory": "PriceDate", "InventorySnapshots": "SnapshotDate"}


@dataclass(frozen=True)
class EtlSettings:
    database_url: str = field(default_factory=lambda: os.environ.get(
        "RETAIL_DATABASE_URL", "postgresql+psycopg2://retail:retail@localhost:5432/retail"))
    odata_url: str = field(default_factory=lambda: os.environ.get("ODATA_BASE_URL", "http://mock-odata:8080/odata"))
    work_dir: Path = field(default_factory=lambda: Path(os.environ.get("ETL_WORK_DIR", "/opt/airflow/etl-data")))
    incoming_dir: Path = field(default_factory=lambda: Path(os.environ.get("CSV_INCOMING_DIR", "/opt/airflow/incoming")))
    # Re-read this many days before the watermark to pick up late-arriving corrections.
    overlap_days: int = field(default_factory=lambda: int(os.environ.get("ETL_OVERLAP_DAYS", "3")))
    # Fail the run if more than this share of an entity's records is invalid.
    max_invalid_ratio: float = field(default_factory=lambda: float(os.environ.get("ETL_MAX_INVALID_RATIO", "0.05")))
    request_timeout: int = 60


def engine(settings: EtlSettings | None = None) -> Engine:
    s = settings or EtlSettings()
    return create_engine(s.database_url, pool_pre_ping=True)


def run_dir(settings: EtlSettings, pipeline_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_." else "_" for c in pipeline_id)
    d = settings.work_dir / safe
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_frames(frames: dict[str, pd.DataFrame], directory: Path) -> dict[str, str]:
    directory.mkdir(parents=True, exist_ok=True)
    paths = {}
    for name, df in frames.items():
        p = directory / f"{name}.pkl"
        df.to_pickle(p)
        paths[name] = str(p)
    return paths


def load_frames(paths: dict[str, str]) -> dict[str, pd.DataFrame]:
    return {name: pd.read_pickle(p) for name, p in paths.items()}


def _py(v):
    """Convert pandas/numpy scalars to types psycopg2 can adapt."""
    if v is None or (not isinstance(v, (str, bytes)) and pd.isna(v)):
        return None
    if isinstance(v, pd.Timestamp):
        return v.to_pydatetime()
    if hasattr(v, "item"):  # numpy scalar
        return v.item()
    return v


def upsert(conn, table: str, df: pd.DataFrame, key: list[str], update: list[str] | None = None,
           page_size: int = 5000) -> int:
    """Idempotent bulk insert: INSERT ... ON CONFLICT (key) DO UPDATE."""
    if df.empty:
        return 0
    cols = list(df.columns)
    update = [c for c in (update if update is not None else cols) if c not in key]
    set_clause = ", ".join(f"{c} = EXCLUDED.{c}" for c in update) or None
    conflict = f"ON CONFLICT ({', '.join(key)}) " + (f"DO UPDATE SET {set_clause}" if set_clause else "DO NOTHING")
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s {conflict}"
    rows = [tuple(_py(v) for v in r) for r in df.itertuples(index=False, name=None)]
    raw = conn.connection.dbapi_connection if hasattr(conn.connection, "dbapi_connection") else conn.connection
    with raw.cursor() as cur:
        execute_values(cur, sql, rows, page_size=page_size)
    return len(rows)


def insert_json_rows(conn, table: str, rows: list[dict], json_cols: set[str]) -> None:
    if not rows:
        return
    cols = list(rows[0])
    sql = f"INSERT INTO {table} ({', '.join(cols)}) VALUES %s"
    values = [tuple(Json(r[c], dumps=lambda o: json.dumps(o, default=str)) if c in json_cols else r[c] for c in cols)
              for r in rows]
    raw = conn.connection.dbapi_connection if hasattr(conn.connection, "dbapi_connection") else conn.connection
    with raw.cursor() as cur:
        execute_values(cur, sql, values, page_size=2000)


def get_watermarks(eng: Engine) -> dict[str, str]:
    with eng.connect() as conn:
        return dict(conn.execute(text("SELECT entity, last_value FROM etl_watermarks")).fetchall())
