"""Settings and feature flag API routes.

Endpoints:
    GET  /api/v1/settings              — Current app settings
    PUT  /api/v1/settings              — Update settings (Admin)
    GET  /api/v1/settings/flags        — All feature flags
    PUT  /api/v1/settings/flags/{name} — Toggle flag (Admin)
    GET  /api/v1/settings/profiles     — Extraction profiles summary
"""
import logging

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.config import get_settings
from backend.dependencies import execute_sql
from backend.middleware.auth import require_role
from backend.models.domain import UserRole
from backend.models.requests import FlagUpdateRequest, SettingsUpdateRequest
from backend.models.responses import APIResponse
from backend.services.feature_flag_cache import flag_cache
from backend.services.healthcare_profiles import list_profiles
from backend.services.hipaa_audit import audit_service

logger = logging.getLogger("healthcontracts")
router = APIRouter(prefix="/v1/settings", tags=["settings"])


# --------------------------------------------------------------------------
# GET /settings
# --------------------------------------------------------------------------
@router.get(
    "",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def get_app_settings():
    """Return current application settings and environment info."""
    s = get_settings()
    return APIResponse(
        status="success",
        data={
            "warehouse_config": {
                "warehouse_id": s.sql_warehouse_id or "auto",
                "http_path": s.sql_warehouse_http_path or "auto",
            },
            "timeouts": {
                "sql_statement_timeout_sec": 120,
                "circuit_breaker_failure_threshold": 5,
                "circuit_breaker_recovery_sec": 60,
            },
            "extraction_defaults": {
                "default_profile": "general_healthcare",
                "default_batch_size": 25,
                "healthcare_mode": True,
                "max_upload_size_mb": 500,
            },
            "environment": {
                "catalog": s.app_catalog,
                "schema": s.app_schema,
                "customer_catalog": s.customer_catalog,
                "customer_schema": s.customer_schema,
                "volume_path": s.volume_path,
            },
        },
    )


# --------------------------------------------------------------------------
# PUT /settings
# --------------------------------------------------------------------------
@router.put(
    "",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def update_settings(body: SettingsUpdateRequest, request: Request):
    """Update application settings. Admin only."""
    user_id = getattr(request.state, "user_id", "anonymous")

    # Settings are persisted via environment variables / app.yaml;
    # this endpoint validates and logs the intent. Actual persistence
    # requires a re-deploy via DABs. For dynamic settings, use feature flags.
    await audit_service.log_event(
        event_type="SETTINGS_UPDATED",
        user_identity=user_id,
        user_role="ADMIN",
        resource_type="settings",
        resource_id="app_settings",
        action="update_settings",
        details={"settings": body.settings},
    )

    return APIResponse(
        status="success",
        data={"message": "Settings update logged. Dynamic changes applied via feature flags; static changes require re-deploy."},
    )


# --------------------------------------------------------------------------
# GET /settings/flags
# --------------------------------------------------------------------------
@router.get(
    "/flags",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def get_feature_flags():
    """Return all feature flags with current state."""
    s = get_settings()
    rows = await execute_sql(
        f"SELECT flag_name, enabled, rollout_pct, description, user_allowlist, "
        f"updated_at "
        f"FROM {s.app_catalog}.{s.app_schema}.feature_flags "
        f"ORDER BY flag_name"
    )
    return APIResponse(status="success", data=rows)


# --------------------------------------------------------------------------
# PUT /settings/flags/{flag_name}
# --------------------------------------------------------------------------
@router.put(
    "/flags/{flag_name}",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.ADMIN))],
)
async def update_flag(flag_name: str, body: FlagUpdateRequest, request: Request):
    """Toggle a feature flag. Admin only. Invalidates cache immediately."""
    user_id = getattr(request.state, "user_id", "anonymous")
    s = get_settings()

    # Verify flag exists (parameterized to prevent SQL injection)
    existing = await execute_sql(
        f"SELECT flag_name FROM {s.app_catalog}.{s.app_schema}.feature_flags "
        f"WHERE flag_name = :flag_name",
        parameters={"flag_name": flag_name},
    )
    if not existing:
        raise HTTPException(status_code=404, detail=f"Flag '{flag_name}' not found")

    # Build SET clause with parameterized values
    set_parts = ["updated_at = current_timestamp()"]
    params: dict[str, str] = {"flag_name": flag_name}
    if body.enabled is not None:
        set_parts.append("enabled = :enabled")
        params["enabled"] = str(body.enabled).lower()
    if body.rollout_pct is not None:
        set_parts.append("rollout_pct = :rollout_pct")
        params["rollout_pct"] = str(body.rollout_pct)

    await execute_sql(
        f"UPDATE {s.app_catalog}.{s.app_schema}.feature_flags "
        f"SET {', '.join(set_parts)} "
        f"WHERE flag_name = :flag_name",
        parameters=params,
    )

    # Invalidate cache immediately
    await flag_cache.invalidate()

    await audit_service.log_event(
        event_type="FLAG_UPDATED",
        user_identity=user_id,
        user_role="ADMIN",
        resource_type="feature_flag",
        resource_id=flag_name,
        action="update_flag",
        details={"enabled": body.enabled, "rollout_pct": body.rollout_pct},
    )

    return APIResponse(
        status="success",
        data={"flag_name": flag_name, "enabled": body.enabled, "rollout_pct": body.rollout_pct},
    )


# --------------------------------------------------------------------------
# GET /settings/profiles
# --------------------------------------------------------------------------
@router.get(
    "/profiles",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def get_profiles():
    """Return available extraction profiles."""
    return APIResponse(status="success", data={"profiles": list_profiles()})
