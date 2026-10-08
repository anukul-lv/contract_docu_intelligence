"""Review workbench API routes.

Endpoints:
    GET  /api/v1/review/queue                  — Paginated review queue
    POST /api/v1/review/{review_id}/claim      — Claim item (optimistic lock)
    POST /api/v1/review/{review_id}/approve    — Approve item
    POST /api/v1/review/{review_id}/correct    — Correct with new value
    POST /api/v1/review/{review_id}/flag       — Flag for attention
    POST /api/v1/review/batch-approve          — Batch approve non-critical
    POST /api/v1/review/{review_id}/revert     — Revert to AI value
    GET  /api/v1/review/stats                  — Review dashboard stats
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from backend.middleware.auth import require_role
from backend.models.domain import UserRole
from backend.models.requests import (
    BatchApproveRequest,
    ReviewApproveRequest,
    ReviewClaimRequest,
    ReviewCorrectRequest,
    ReviewFlagRequest,
    ReviewRevertRequest,
)
from backend.models.responses import APIResponse, PaginationMeta
from backend.services.hipaa_audit import audit_service
from backend.services.review_service import review_service

logger = logging.getLogger("healthcontracts")
router = APIRouter(prefix="/v1/review", tags=["review"])


# --------------------------------------------------------------------------
# GET /queue
# --------------------------------------------------------------------------
@router.get(
    "/queue",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def review_queue(
    cursor: Optional[str] = None,
    limit: int = 50,
    status: Optional[str] = None,
    priority: Optional[str] = None,
    assigned_to: Optional[str] = None,
    field_class: Optional[str] = None,
):
    """Cursor-paginated review queue with filters."""
    items, next_cursor, total = await review_service.get_queue(
        cursor=cursor,
        limit=min(limit, 100),
        status=status,
        priority=priority,
        assigned_to=assigned_to,
        field_class=field_class,
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
# POST /{review_id}/claim
# --------------------------------------------------------------------------
@router.post(
    "/{review_id}/claim",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.REVIEWER))],
)
async def claim_review(review_id: str, body: ReviewClaimRequest, request: Request):
    """Claim a review item with optimistic locking."""
    user_id = getattr(request.state, "user_id", "anonymous")
    ok = await review_service.claim(review_id, body.expected_version, user_id)
    if not ok:
        raise HTTPException(
            status_code=409,
            detail="Version conflict — item was modified by another reviewer. Please refresh.",
        )
    await _audit(request, "REVIEW_CLAIMED", review_id)
    return APIResponse(status="success", data={"review_id": review_id, "state": "IN_REVIEW"})


# --------------------------------------------------------------------------
# POST /{review_id}/approve
# --------------------------------------------------------------------------
@router.post(
    "/{review_id}/approve",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.REVIEWER))],
)
async def approve_review(review_id: str, body: ReviewApproveRequest, request: Request):
    user_id = getattr(request.state, "user_id", "anonymous")
    ok = await review_service.approve(
        review_id, body.expected_version, user_id, comment=body.comment
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Version conflict — please refresh.")
    await _audit(request, "REVIEW_APPROVED", review_id)
    return APIResponse(status="success", data={"review_id": review_id, "state": "APPROVED"})


# --------------------------------------------------------------------------
# POST /{review_id}/correct
# --------------------------------------------------------------------------
@router.post(
    "/{review_id}/correct",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.REVIEWER))],
)
async def correct_review(review_id: str, body: ReviewCorrectRequest, request: Request):
    user_id = getattr(request.state, "user_id", "anonymous")
    ok = await review_service.correct(
        review_id, body.expected_version, user_id,
        corrected_value=body.corrected_value,
        correction_reason=body.correction_reason,
        comment=body.comment,
    )
    if not ok:
        raise HTTPException(status_code=409, detail="Version conflict — please refresh.")
    await _audit(request, "REVIEW_CORRECTED", review_id)
    return APIResponse(status="success", data={"review_id": review_id, "state": "CORRECTED"})


# --------------------------------------------------------------------------
# POST /{review_id}/flag
# --------------------------------------------------------------------------
@router.post(
    "/{review_id}/flag",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.REVIEWER))],
)
async def flag_review(review_id: str, body: ReviewFlagRequest, request: Request):
    user_id = getattr(request.state, "user_id", "anonymous")
    ok = await review_service.flag(review_id, body.expected_version, user_id, body.reason)
    if not ok:
        raise HTTPException(status_code=409, detail="Version conflict — please refresh.")
    await _audit(request, "REVIEW_FLAGGED", review_id)
    return APIResponse(status="success", data={"review_id": review_id, "state": "FLAGGED"})


# --------------------------------------------------------------------------
# POST /batch-approve
# --------------------------------------------------------------------------
@router.post(
    "/batch-approve",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.REVIEWER))],
)
async def batch_approve(body: BatchApproveRequest, request: Request):
    """Batch approve non-critical fields above confidence threshold."""
    user_id = getattr(request.state, "user_id", "anonymous")
    result = await review_service.batch_approve(
        review_ids=body.review_ids,
        min_confidence=body.min_confidence,
        reviewer=user_id,
    )
    await _audit(request, "BATCH_APPROVE", ",".join(body.review_ids))
    return APIResponse(status="success", data=result)


# --------------------------------------------------------------------------
# POST /{review_id}/revert
# --------------------------------------------------------------------------
@router.post(
    "/{review_id}/revert",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.REVIEWER))],
)
async def revert_review(review_id: str, body: ReviewRevertRequest, request: Request):
    user_id = getattr(request.state, "user_id", "anonymous")
    ok = await review_service.revert(review_id, user_id, body.reason)
    if not ok:
        raise HTTPException(status_code=404, detail="Review item not found.")
    await _audit(request, "REVIEW_REVERTED", review_id)
    return APIResponse(status="success", data={"review_id": review_id, "state": "PENDING"})


# --------------------------------------------------------------------------
# GET /stats
# --------------------------------------------------------------------------
@router.get(
    "/stats",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def review_stats():
    stats = await review_service.get_stats()
    return APIResponse(status="success", data=stats)


# --------------------------------------------------------------------------
# Helpers
# --------------------------------------------------------------------------
async def _audit(request: Request, event_type: str, resource_id: str) -> None:
    user_id = getattr(request.state, "user_id", "anonymous")
    role = getattr(request.state, "user_role", UserRole.VIEWER)
    await audit_service.log_event(
        event_type=event_type,
        user_identity=user_id,
        user_role=role.value if hasattr(role, "value") else str(role),
        resource_type="review_item",
        resource_id=resource_id,
        action=event_type.lower(),
    )
