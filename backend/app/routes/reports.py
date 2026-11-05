"""CSV / Excel report downloads."""

from __future__ import annotations

from datetime import date
from typing import Literal

from fastapi import APIRouter, Depends, Query
from fastapi.responses import Response
from sqlalchemy.engine import Connection

from ..database import get_db
from ..schemas.common import ERROR_RESPONSES
from ..services import report_service

router = APIRouter(prefix="/api/reports", tags=["reports"], responses=ERROR_RESPONSES)


@router.get("", summary="Available reports")
def list_reports():
    return report_service.available_reports()


@router.get("/{report}", summary="Report preview (JSON) or download (CSV/Excel)")
def report(report: str, format: Literal["json", "csv", "xlsx"] = "json", start: date | None = None,
           end: date | None = None, category: list[str] | None = Query(None), sku: str | None = None,
           sort: str | None = None, descending: bool = True, limit: int = Query(200, ge=1, le=5000),
           conn: Connection = Depends(get_db)):
    req = report_service.ReportRequest(start=start, end=end, category=category, sku=sku, sort=sort,
                                       descending=descending)
    df = report_service.build(conn, report, req)
    if format == "json":
        return {"report": report, "total_rows": len(df), "columns": list(df.columns),
                "rows": df.head(limit).astype(object).where(df.head(limit).notna(), None).to_dict(orient="records")}
    body, media = report_service.to_bytes(df, format, report)
    stamp = date.today().isoformat()
    return Response(body, media_type=media,
                    headers={"Content-Disposition": f'attachment; filename="{report}_{stamp}.{format}"'})
