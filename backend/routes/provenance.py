"""Provenance routes — Evidence chain drilldown API.

GET /api/v1/provenance/{document_version_id}/{field_name}
  Returns: current state, review history, extraction output,
  confidence breakdown, citations, source file, amendment chain.
"""
from __future__ import annotations

import logging
from dataclasses import asdict

from fastapi import APIRouter, Depends, HTTPException

from backend.dependencies import get_current_user
from backend.middleware.auth import require_role
from backend.models.domain import UserRole
from backend.models.responses import APIResponse
from backend.services.amendment_engine import AmendmentEngine
from backend.services.provenance_service import ProvenanceService

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/v1/provenance", tags=["provenance"])


@router.get("/{document_version_id}/{field_name}")
async def get_provenance(
    document_version_id: str,
    field_name: str,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.VIEWER)),
) -> APIResponse:
    """Full evidence chain for any extracted value.

    Response includes:
    - current_state: trusted value, review status, confidence score
    - review_actions: immutable history of approvals, corrections, flags
    - extracted_value: original AI extraction with profile
    - confidence_explanation: 4-signal breakdown (50/20/20/10)
    - citations: page/section/text references to source document
    - source_file: file metadata (name, path, checksum, upload date)
    - amendment_chain: supersession chain with status and dates
    """
    svc = ProvenanceService()
    result = await svc.get_provenance(document_version_id, field_name)

    if result is None:
        raise HTTPException(status_code=404, detail="Field not found")

    return APIResponse(
        status="success",
        data=asdict(result),
    )


@router.get("/{document_version_id}/chain")
async def get_amendment_chain(
    document_version_id: str,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.VIEWER)),
) -> APIResponse:
    """Get the full amendment/supersession chain for a document.

    Returns the resolved current-in-force state with field-level provenance.
    """
    engine = AmendmentEngine()
    result = await engine.resolve_current_state(document_version_id)

    return APIResponse(
        status="success",
        data={
            "document_family_id": result.document_family_id,
            "chain_depth": result.chain_depth,
            "fields": {
                name: asdict(res) for name, res in result.fields.items()
            },
            "relationships": [
                asdict(r) for r in result.relationships
            ],
        },
    )


@router.post("/{document_version_id}/detect")
async def detect_amendments(
    document_version_id: str,
    user: dict = Depends(get_current_user),
    _role: str = Depends(require_role(UserRole.OPERATOR)),
) -> APIResponse:
    """Detect amendment/supersession relationships for a newly extracted document.

    Typically called automatically during extraction, but can be triggered manually.
    """
    engine = AmendmentEngine()
    detected = await engine.detect_relationships(document_version_id)

    return APIResponse(
        status="success",
        data={
            "document_version_id": document_version_id,
            "detected_relationships": detected,
            "count": len(detected),
        },
    )
