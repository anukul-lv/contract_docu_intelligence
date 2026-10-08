"""Authentication and RBAC middleware for Databricks App OAuth.

Extracts user identity from Databricks App request headers and resolves
role from UC group membership.

Role hierarchy: Admin > Reviewer > Operator > Viewer

RBAC permissions:
  Viewer   — Dashboard + read-only chat history
  Operator — Viewer + upload + extraction
  Reviewer — Operator + review queue actions
  Admin    — Reviewer + settings + audit + PHI vault
"""
import logging
from typing import Callable

from fastapi import HTTPException, Request
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.responses import Response

from backend.models.domain import ROLE_HIERARCHY, UserRole

logger = logging.getLogger("healthcontracts")

# Mapping from Databricks UC group names to application roles
GROUP_TO_ROLE: dict[str, UserRole] = {
    "healthcare_admin": UserRole.ADMIN,
    "healthcare_reviewer": UserRole.REVIEWER,
    "healthcare_operator": UserRole.OPERATOR,
    "healthcare_viewer": UserRole.VIEWER,
}


class AuthMiddleware(BaseHTTPMiddleware):
    """Extract user identity from Databricks App request headers.

    Databricks Apps inject the following headers automatically:
      - X-Forwarded-Email: user's email
      - X-Forwarded-Preferred-Username: display name
      - X-Forwarded-Groups: comma-separated UC groups
    """

    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        # Skip auth for health check and docs
        if request.url.path in ("/api/health", "/api/docs", "/openapi.json"):
            return await call_next(request)

        # Extract user identity from Databricks App headers
        user_email = request.headers.get(
            "X-Forwarded-Email",
            request.headers.get("x-forwarded-email", ""),
        )
        user_name = request.headers.get(
            "X-Forwarded-Preferred-Username",
            request.headers.get("x-forwarded-preferred-username", user_email),
        )
        groups_header = request.headers.get(
            "X-Forwarded-Groups",
            request.headers.get("x-forwarded-groups", ""),
        )
        user_groups = [g.strip() for g in groups_header.split(",") if g.strip()]

        # Resolve the highest role from group membership
        resolved_role = UserRole.VIEWER  # default
        for group in user_groups:
            role = GROUP_TO_ROLE.get(group)
            if role and ROLE_HIERARCHY.index(role) > ROLE_HIERARCHY.index(resolved_role):
                resolved_role = role

        # Inject into request state for downstream access
        request.state.user_id = user_email or "anonymous"
        request.state.user_name = user_name or "anonymous"
        request.state.user_role = resolved_role
        request.state.user_groups = user_groups

        return await call_next(request)


def require_role(minimum_role: UserRole) -> Callable:
    """FastAPI dependency that checks the user has at least the given role.

    Usage:
        @router.post("/admin/settings", dependencies=[Depends(require_role(UserRole.ADMIN))])
    """

    async def _check(request: Request) -> None:
        current_role: UserRole = getattr(request.state, "user_role", UserRole.VIEWER)
        if ROLE_HIERARCHY.index(current_role) < ROLE_HIERARCHY.index(minimum_role):
            logger.warning(
                "Access denied: user=%s role=%s required=%s path=%s",
                getattr(request.state, "user_id", "unknown"),
                current_role.value,
                minimum_role.value,
                request.url.path,
            )
            raise HTTPException(
                status_code=403,
                detail=f"Requires {minimum_role.value} role or higher",
            )

    return _check
