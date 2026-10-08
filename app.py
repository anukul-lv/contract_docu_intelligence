"""HealthContracts AI — FastAPI Application Entrypoint.

Production-grade app shell with security headers, CORS, authentication,
HIPAA audit logging, feature flag cache, and structured JSON logging.
"""
import json
import logging
import os
import sys
import time
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from backend.config import get_settings
from backend.middleware.auth import AuthMiddleware
from backend.middleware.audit_logger import AuditLoggerMiddleware
from backend.middleware.rate_limiter import RateLimitMiddleware
from backend.middleware.security_headers import SecurityHeadersMiddleware
from backend.middleware.timing import TimingMiddleware
from backend.routes import api_router
from backend.services.circuit_breaker import sql_warehouse_breaker
from backend.services.feature_flag_cache import flag_cache

# ---------------------------------------------------------------------------
# Structured JSON logging to stdout (captured by Databricks App)
# ---------------------------------------------------------------------------


class JSONFormatter(logging.Formatter):
    """Emit log records as structured JSON."""

    def format(self, record: logging.LogRecord) -> str:
        log_entry = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "service": "fastapi",
            "logger": record.name,
            "message": record.getMessage(),
        }
        if record.exc_info and record.exc_info[1]:
            log_entry["exception"] = str(record.exc_info[1])
        return json.dumps(log_entry)


handler = logging.StreamHandler(sys.stdout)
handler.setFormatter(JSONFormatter())
logging.getLogger("healthcontracts").addHandler(handler)
logging.getLogger("healthcontracts").setLevel(logging.INFO)

logger = logging.getLogger("healthcontracts")
settings = get_settings()

# Suppress DEBUG in production
if settings.environment == "prod":
    logging.getLogger("healthcontracts").setLevel(logging.INFO)
else:
    logging.getLogger("healthcontracts").setLevel(logging.DEBUG)


# ---------------------------------------------------------------------------
# Application lifespan (startup / shutdown)
# ---------------------------------------------------------------------------
_start_time: float = 0.0


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Startup: initialize feature flag cache. Shutdown: cleanup."""
    global _start_time
    _start_time = time.time()
    logger.info(
        "HealthContracts AI starting (env=%s, catalog=%s.%s)",
        settings.environment,
        settings.app_catalog,
        settings.app_schema,
    )
    try:
        await flag_cache.start()
        logger.info("Feature flag cache initialized")
    except Exception as exc:
        logger.warning("Feature flag cache failed to initialize: %s", exc)

    yield  # App is running

    logger.info("HealthContracts AI shutting down")


# ---------------------------------------------------------------------------
# FastAPI Application
# ---------------------------------------------------------------------------
app = FastAPI(
    title="HealthContracts AI",
    version="1.0.0",
    docs_url="/api/docs" if settings.environment != "prod" else None,
    redoc_url=None,
    lifespan=lifespan,
)

# Middleware is applied in reverse order (last added = first executed)
# Order: Timing -> RateLimit -> Auth -> Audit -> Security Headers -> CORS -> Routes
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(AuditLoggerMiddleware)
app.add_middleware(AuthMiddleware)
app.add_middleware(RateLimitMiddleware)
app.add_middleware(TimingMiddleware)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Databricks App handles origin restrictions
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Mount all API routes
app.include_router(api_router)

# ---------------------------------------------------------------------------
# Static files — serve the built React frontend
# ---------------------------------------------------------------------------
_STATIC_DIR = Path(__file__).parent / "static"

if _STATIC_DIR.is_dir():
    app.mount("/assets", StaticFiles(directory=_STATIC_DIR / "assets"), name="assets")

    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """SPA fallback — serve index.html for all non-API routes.

        This allows React Router to handle client-side routing
        (e.g. /ingest, /explore, /chat, /admin).
        """
        # If the path matches a real file in static/, serve it
        file_path = _STATIC_DIR / full_path
        if file_path.is_file():
            return FileResponse(file_path)
        # Otherwise, serve index.html for client-side routing
        return FileResponse(_STATIC_DIR / "index.html")
else:
    logger.warning("Static directory not found at %s — frontend will not be served", _STATIC_DIR)


# ---------------------------------------------------------------------------
# Health Check (full component status)
# ---------------------------------------------------------------------------
@app.get("/api/health")
async def health_check():
    """Full health check with component statuses."""
    uptime_sec = time.time() - _start_time if _start_time else 0

    components = {
        "app": {"status": "ok", "uptime_sec": round(uptime_sec, 1)},
        "sql_warehouse": {
            "status": "ok" if sql_warehouse_breaker.state == "closed" else "degraded",
        },
        "feature_flags": {
            "status": "ok",
            "flags_loaded": len(flag_cache.get_all_flags()),
        },
    }

    # Determine overall status
    statuses = [c["status"] for c in components.values()]
    if all(s == "ok" for s in statuses):
        overall = "healthy"
    elif any(s == "unavailable" for s in statuses):
        overall = "unhealthy"
    else:
        overall = "degraded"

    return {
        "status": overall,
        "components": components,
        "version": "1.0.0",
        "environment": settings.environment,
    }
