"""PostgreSQL connection handling."""

from __future__ import annotations

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import create_engine
from sqlalchemy.engine import Connection, Engine

from .config import get_settings


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True, pool_size=5, max_overflow=10)


def get_db() -> Iterator[Connection]:
    """FastAPI dependency: one connection (and transaction) per request."""
    with get_engine().begin() as conn:
        yield conn
