from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Connection


def fetch_all(conn: Connection, sql: str, **params: Any) -> list[dict]:
    return [dict(r) for r in conn.execute(text(sql), params).mappings().all()]


def fetch_one(conn: Connection, sql: str, **params: Any) -> dict | None:
    row = conn.execute(text(sql), params).mappings().first()
    return dict(row) if row else None


def scalar(conn: Connection, sql: str, **params: Any):
    return conn.execute(text(sql), params).scalar()
