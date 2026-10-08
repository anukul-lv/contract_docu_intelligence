"""Automatic HIPAA audit logging middleware.

Captures every API request and writes to the hipaa_audit_log table
via the HIPAAAuditService. PHI access is flagged when the endpoint
touches phi_vault or PHI-marked fields.
"""
import logging

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from backend.services.hipaa_audit import audit_service

logger = logging.getLogger("healthcontracts")

# Paths that access PHI data (trigger phi_accessed=True in audit log)
PHI_PATHS = {"/api/phi", "/api/phi-vault"}

# Paths to skip auditing (high-frequency, no business value)
SKIP_PATHS = {"/api/health", "/api/docs", "/openapi.json", "/favicon.ico"}


class AuditLoggerMiddleware(BaseHTTPMiddleware):
    """Automatically audit-log every API request."""

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        path = request.url.path

        # Only audit actual API endpoints — skip static files, SPA fallback,
        # assets, and non-business paths. This prevents audit SQL failures
        # from tripping the circuit breaker and blocking real API calls.
        if not path.startswith("/api/") or path in SKIP_PATHS:
            return await call_next(request)

        response = await call_next(request)

        # Fire-and-forget audit log (don't block the response)
        try:
            user_id = getattr(request.state, "user_id", "anonymous")
            user_role = getattr(request.state, "user_role", None)
            role_str = user_role.value if user_role else "unknown"
            request_id = getattr(request.state, "request_id", None)
            phi_accessed = any(path.startswith(p) for p in PHI_PATHS)

            await audit_service.log_event(
                event_type="API_REQUEST",
                user_identity=user_id,
                user_role=role_str,
                resource_type="api_endpoint",
                resource_id=path,
                action=f"{request.method} {path}",
                phi_accessed=phi_accessed,
                source_ip=request.client.host if request.client else None,
                request_id=request_id,
                details={
                    "method": request.method,
                    "status_code": response.status_code,
                    "query_params": str(request.query_params) if request.query_params else None,
                },
                outcome="SUCCESS" if response.status_code < 400 else "FAILURE",
            )
        except Exception as exc:
            # Never let audit failures break the request
            logger.error("Audit middleware error: %s", exc)

        return response
