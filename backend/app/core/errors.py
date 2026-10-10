"""Consistent error envelope used across every API response: {code, message, trace_id}."""

from __future__ import annotations

import uuid

from fastapi import Request, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel


class ErrorEnvelope(BaseModel):
    code: str
    message: str
    trace_id: str


class AppError(Exception):
    def __init__(self, code: str, message: str, status_code: int = status.HTTP_400_BAD_REQUEST):
        self.code = code
        self.message = message
        self.status_code = status_code
        super().__init__(message)


async def app_error_handler(request: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    envelope = ErrorEnvelope(code=exc.code, message=exc.message, trace_id=trace_id)
    return JSONResponse(status_code=exc.status_code, content=envelope.model_dump())


async def unhandled_error_handler(request: Request, exc: Exception) -> JSONResponse:
    trace_id = getattr(request.state, "trace_id", str(uuid.uuid4()))
    envelope = ErrorEnvelope(code="internal_error", message=str(exc), trace_id=trace_id)
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, content=envelope.model_dump()
    )
