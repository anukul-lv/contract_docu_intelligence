"""Middleware components for HealthContracts AI."""
from backend.middleware.auth import AuthMiddleware, require_role
from backend.middleware.security_headers import SecurityHeadersMiddleware
from backend.middleware.timing import TimingMiddleware
from backend.middleware.audit_logger import AuditLoggerMiddleware

__all__ = [
    "AuthMiddleware",
    "SecurityHeadersMiddleware",
    "TimingMiddleware",
    "AuditLoggerMiddleware",
    "require_role",
]
