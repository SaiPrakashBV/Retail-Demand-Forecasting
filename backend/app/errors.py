"""Readable, consistent error responses: {"error": {"code", "message", "details"}}."""

from __future__ import annotations

import logging
import uuid

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from sqlalchemy.exc import OperationalError, ProgrammingError
from starlette.exceptions import HTTPException as StarletteHTTPException

log = logging.getLogger("retail.api")


class AppError(Exception):
    def __init__(self, status: int, code: str, message: str, details: dict | None = None):
        super().__init__(message)
        self.status, self.code, self.message, self.details = status, code, message, details or {}


class NotFound(AppError):
    def __init__(self, message: str, **details):
        super().__init__(404, "not_found", message, details)


class Unavailable(AppError):
    def __init__(self, message: str, code: str = "unavailable", **details):
        super().__init__(503, code, message, details)


def _body(code: str, message: str, details: dict | None = None) -> dict:
    return {"error": {"code": code, "message": message, "details": details or {}}}


def install_error_handlers(app: FastAPI) -> None:
    @app.exception_handler(AppError)
    async def app_error(_: Request, exc: AppError):
        return JSONResponse(_body(exc.code, exc.message, exc.details), status_code=exc.status)

    @app.exception_handler(RequestValidationError)
    async def validation_error(_: Request, exc: RequestValidationError):
        problems = [f"{'.'.join(str(p) for p in e['loc'] if p not in ('query', 'body', 'path'))}: {e['msg']}"
                    for e in exc.errors()]
        return JSONResponse(_body("invalid_request", "Invalid request parameters: " + "; ".join(problems),
                                  {"errors": problems}), status_code=422)

    @app.exception_handler(StarletteHTTPException)
    async def http_error(_: Request, exc: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed"}.get(exc.status_code, "http_error")
        return JSONResponse(_body(code, str(exc.detail)), status_code=exc.status_code)

    @app.exception_handler(OperationalError)
    async def db_down(_: Request, exc: OperationalError):
        log.error("Database error: %s", exc)
        return JSONResponse(_body("database_unavailable",
                                  "The database is not reachable right now. Check that PostgreSQL is running."),
                            status_code=503)

    @app.exception_handler(ProgrammingError)
    async def db_schema(_: Request, exc: ProgrammingError):
        log.error("Database schema error: %s", exc)
        return JSONResponse(_body("database_not_ready",
                                  "The database schema is missing or out of date. Run the migrations "
                                  "(the 'migrate' service in Docker Compose)."), status_code=503)

    @app.exception_handler(Exception)
    async def unexpected(_: Request, exc: Exception):
        ref = uuid.uuid4().hex[:8]
        log.exception("Unhandled error [%s]", ref)
        return JSONResponse(_body("internal_error", f"Unexpected server error (reference {ref}). "
                                  "The details are in the API logs.", {"reference": ref}), status_code=500)
