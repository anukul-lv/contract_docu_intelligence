"""Security headers middleware — hardened but Databricks-App-compatible.

Databricks Apps are embedded in an iframe by the workspace UI at
adb-<id>.<region>.azuredatabricks.net. Key constraints:
  - Do NOT set X-Frame-Options or frame-ancestors — the Databricks
    proxy handles framing security. Custom frame directives break the
    iframe because CSP wildcards can't match multi-level subdomains.
  - Do NOT restrict connect-src beyond 'self' — the proxy rewrites
    API origins.
"""
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

# Safe headers that don't interfere with Databricks App iframe embedding
SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-XSS-Protection": "1; mode=block",
    "Referrer-Policy": "strict-origin-when-cross-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=()",
}


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    """Inject safe security headers on every response.

    Deliberately omits X-Frame-Options, frame-ancestors CSP, and
    Strict-Transport-Security — the Databricks App proxy manages those.
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        for header, value in SECURITY_HEADERS.items():
            response.headers[header] = value
        return response
