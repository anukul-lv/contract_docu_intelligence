"""Contract explorer API routes.

Endpoints:
    GET  /api/v1/explorer/contracts              — Paginated contract list with filters
    GET  /api/v1/explorer/contracts/{family_id}  — Contract detail (all fields + trust badges)
    GET  /api/v1/explorer/filters                — Distinct values for filter dropdowns
    GET  /api/v1/explorer/dashboard              — Pre-aggregated dashboard widget data
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException

from backend.middleware.auth import require_role
from backend.models.domain import UserRole
from backend.models.responses import APIResponse, PaginationMeta
from backend.services.explorer_service import explorer_service

logger = logging.getLogger("healthcontracts")
router = APIRouter(prefix="/v1/explorer", tags=["explorer"])


# --------------------------------------------------------------------------
# GET /contracts
# --------------------------------------------------------------------------
@router.get(
    "/contracts",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def list_contracts(
    cursor: Optional[str] = None,
    limit: int = 25,
    contract_type: Optional[str] = None,
    state: Optional[str] = None,
    status: Optional[str] = None,
    reimbursement_method: Optional[str] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    min_confidence: Optional[float] = None,
    max_confidence: Optional[float] = None,
):
    """Paginated contract card list with full filter support."""
    items, next_cursor, total = await explorer_service.list_contracts(
        cursor=cursor,
        limit=min(limit, 100),
        contract_type=contract_type,
        state=state,
        status=status,
        reimbursement_method=reimbursement_method,
        date_from=date_from,
        date_to=date_to,
        min_confidence=min_confidence,
        max_confidence=max_confidence,
    )
    return APIResponse(
        status="success",
        data=items,
        meta={
            "pagination": PaginationMeta(
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
                total_count=total,
            ).model_dump()
        },
    )


# --------------------------------------------------------------------------
# GET /contracts/{family_id}
# --------------------------------------------------------------------------
@router.get(
    "/contracts/{family_id}",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def contract_detail(family_id: str):
    """Full contract detail: all fields grouped by class with trust badges."""
    detail = await explorer_service.get_contract_detail(family_id)
    if not detail:
        raise HTTPException(status_code=404, detail="Contract not found")
    # Flatten field_groups into a single 'fields' list for the frontend
    fields = []
    for group in detail.get("field_groups", {}).values():
        fields.extend(group)
    detail["fields"] = fields
    return APIResponse(status="success", data=detail)


# --------------------------------------------------------------------------
# GET /filters
# --------------------------------------------------------------------------
@router.get(
    "/filters",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def filter_values():
    """Distinct values for all filter panel dropdowns."""
    values = await explorer_service.get_filter_values()
    return APIResponse(status="success", data=values)


# --------------------------------------------------------------------------
# GET /dashboard
# --------------------------------------------------------------------------
@router.get(
    "/dashboard",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def dashboard_data():
    """Pre-aggregated data for the 5 business dashboard widgets."""
    data = await explorer_service.get_dashboard_data()
    return APIResponse(status="success", data=data)
