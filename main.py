from __future__ import annotations

import time
import uuid
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from starlette.requests import Request
from starlette.responses import Response

from keenchic.api.router import router
from keenchic.core.config import settings
from keenchic.core.logging import configure_logging

log = structlog.get_logger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    configure_logging(settings.LOG_FORMAT, settings.LOG_LEVEL)
    log.info("app.startup", log_format=settings.LOG_FORMAT, log_level=settings.LOG_LEVEL)
    yield
    log.info("app.shutdown")


app = FastAPI(title="Keenchic Inspection API", version="1.0.0", lifespan=lifespan)


@app.middleware("http")
async def logging_middleware(request: Request, call_next) -> Response:
    request_id = uuid.uuid4().hex[:12]
    inspection_name = request.headers.get("X-Inspection-Name")

    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(request_id=request_id)

    log.info(
        "http.request",
        method=request.method,
        path=request.url.path,
        inspection_name=inspection_name,
    )

    start = time.monotonic()
    try:
        response = await call_next(request)
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log.info(
            "http.response",
            status_code=response.status_code,
            duration_ms=duration_ms,
        )
        return response
    except Exception as exc:
        duration_ms = round((time.monotonic() - start) * 1000, 1)
        log.error(
            "http.error",
            status_code=500,
            duration_ms=duration_ms,
            error=str(exc),
        )
        raise


app.include_router(router)

__all__ = ["app"]
