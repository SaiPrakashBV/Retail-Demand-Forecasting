"""Stock and reorder recommendations."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy.engine import Connection

from ..database import get_db
from ..schemas.common import ERROR_RESPONSES
from ..services import reorder_service

router = APIRouter(prefix="/api/inventory", tags=["inventory"], responses=ERROR_RESPONSES)


@router.get("/reorders", summary="Recommended reorders from the latest forecast")
def reorders(
    priority: list[Literal["critical", "high", "medium", "low"]] | None = Query(None),
    category: list[str] | None = Query(None), q: str | None = None,
    actionable_only: bool = Query(True, description="Only products with a suggested order quantity > 0"),
    sort: Literal["priority", "stockout_date", "reorder_quantity", "days_of_cover"] = "priority",
    page: int = Query(1, ge=1), page_size: int = Query(50, ge=1, le=500),
    conn: Connection = Depends(get_db),
):
    return reorder_service.list_reorders(conn, priority=priority, category=category, q=q,
                                         actionable_only=actionable_only, sort=sort, limit=page_size,
                                         offset=(page - 1) * page_size)
