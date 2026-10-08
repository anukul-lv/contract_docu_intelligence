"""Admin API routes — audit log viewer.

Endpoints:
    GET /api/v1/admin/audit-log  — Paginated, filterable HIPAA audit log
"""
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends

from backend.config import get_settings
from backend.dependencies import execute_sql
from backend.middleware.auth import require_role
from backend.models.domain import UserRole
from backend.models.responses import APIResponse, PaginationMeta

logger = logging.getLogger("healthcontracts")
router = APIRouter(prefix="/v1/admin", tags=["admin"])


@router.get(
    "/audit-log",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def get_audit_log(
    cursor: Optional[str] = None,
    limit: int = 100,
    user: Optional[str] = None,
    event_type: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
):
    """Paginated, filterable HIPAA audit log. Admin only."""
    s = get_settings()
    where = []
    params: dict[str, str] = {}

    if user:
        where.append("user_identity = :filter_user")
        params["filter_user"] = user
    if event_type:
        where.append("event_type = :filter_event_type")
        params["filter_event_type"] = event_type
    if date_from:
        where.append("event_timestamp >= TIMESTAMP :date_from")
        params["date_from"] = date_from
    if date_to:
        where.append("event_timestamp <= TIMESTAMP :date_to")
        params["date_to"] = f"{date_to} 23:59:59"
    if cursor:
        try:
            decoded = base64.b64decode(cursor).decode()
            parts = decoded.split("|", 1)
            where.append("(event_timestamp, event_id) < (TIMESTAMP :cursor_ts, :cursor_id)")
            params["cursor_ts"] = parts[0]
            params["cursor_id"] = parts[1]
        except Exception:
            pass

    where_sql = ("WHERE " + " AND ".join(where)) if where else ""
    capped_limit = min(limit, 500)

    rows = await execute_sql(
        f"SELECT event_id, event_timestamp, event_type, user_identity, user_role, "
        f"resource_type, resource_id, action, phi_accessed, source_ip "
        f"FROM {s.app_catalog}.{s.app_schema}.hipaa_audit_log "
        f"{where_sql} ORDER BY event_timestamp DESC, event_id DESC LIMIT {capped_limit + 1}",
        parameters=params if params else None,
    )

    has_more = len(rows) > capped_limit
    items = rows[:capped_limit]
    next_cursor = None
    if has_more and items:
        last = items[-1]
        composite = f"{last.get('event_timestamp', '')}|{last.get('event_id', '')}"
        next_cursor = base64.b64encode(composite.encode()).decode()

    return APIResponse(
        status="success",
        data=items,
        meta={
            "pagination": PaginationMeta(
                next_cursor=next_cursor,
                has_more=has_more,
            ).model_dump()
        },
    )


@router.get(
    "/audit-log/event-types",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def audit_event_types():
    """Return distinct event types for the filter dropdown."""
    s = get_settings()
    rows = await execute_sql(
        f"SELECT DISTINCT event_type FROM {s.app_catalog}.{s.app_schema}.hipaa_audit_log "
        f"ORDER BY event_type"
    )
    return APIResponse(
        status="success",
        data=[r["event_type"] for r in rows],
    )
