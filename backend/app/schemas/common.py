from __future__ import annotations

from typing import Any

from pydantic import BaseModel


class ErrorBody(BaseModel):
    code: str
    message: str
    details: dict[str, Any] = {}


class ErrorResponse(BaseModel):
    error: ErrorBody


ERROR_RESPONSES = {
    404: {"model": ErrorResponse, "description": "Not found"},
    503: {"model": ErrorResponse, "description": "Data or forecast not available yet"},
}
