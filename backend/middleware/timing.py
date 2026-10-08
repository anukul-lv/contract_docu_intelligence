"""Request timing middleware — logs duration and sets X-Request-ID header."""
import logging
import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

logger = logging.getLogger("healthcontracts")

SLOW_REQUEST_THRESHOLD_MS = 5000  # Warn if request takes > 5 seconds


class TimingMiddleware(BaseHTTPMiddleware):
    """Measure request duration and assign a unique request ID."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", str(uuid.uuid4()))
        request.state.request_id = request_id

        start = time.perf_counter()
        response = await call_next(request)
        duration_ms = (time.perf_counter() - start) * 1000

        response.headers["X-Request-ID"] = request_id
        response.headers["X-Response-Time-Ms"] = f"{duration_ms:.1f}"

        log_level = logging.WARNING if duration_ms > SLOW_REQUEST_THRESHOLD_MS else logging.INFO
        logger.log(
            log_level,
            "%s %s -> %d (%.1fms) [%s]",
            request.method,
            request.url.path,
            response.status_code,
            duration_ms,
            request_id,
        )

        return response
