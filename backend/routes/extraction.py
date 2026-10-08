"""Extraction API routes.

Endpoints:
    POST /api/v1/extract/start          — Submit extraction job
    GET  /api/v1/extract/status/{run_id} — Job status + progress
    GET  /api/v1/extract/stream/{run_id} — SSE progress stream
    POST /api/v1/extract/cancel/{run_id} — Cancel running job
    POST /api/v1/extract/retry/{run_id}  — Retry failed documents
    GET  /api/v1/extract/history         — Extraction job history
"""
import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse

from backend.middleware.auth import require_role
from backend.models.domain import UserRole
from backend.models.requests import ExtractionStartRequest
from backend.models.responses import APIResponse, PaginationMeta
from backend.services.extraction_engine import extraction_engine
from backend.services.hipaa_audit import audit_service
from backend.services.job_tracker import job_tracker

logger = logging.getLogger("healthcontracts")
router = APIRouter(prefix="/v1/extract", tags=["extraction"])


# --------------------------------------------------------------------------
# POST /start
# --------------------------------------------------------------------------
@router.post(
    "/start",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.OPERATOR))],
)
async def start_extraction(body: ExtractionStartRequest, request: Request):
    """Submit an extraction job for the selected files."""
    user_id = getattr(request.state, "user_id", "anonymous")

    try:
        result = await extraction_engine.start_extraction(
            volume_path=body.volume_path,
            file_list=body.file_list,
            output_catalog=body.output_catalog,
            output_schema=body.output_schema,
            profile=body.profile,
            auto_enrich=body.auto_enrich,
            healthcare_mode=body.healthcare_mode,
            idempotency_key=body.idempotency_key,
            created_by=user_id,
        )
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))

    # HIPAA audit
    await audit_service.log_event(
        event_type="EXTRACTION_STARTED",
        user_identity=user_id,
        user_role=getattr(request.state, "user_role", UserRole.VIEWER).value,
        resource_type="extraction_job",
        resource_id=result["run_id"],
        action="start_extraction",
        details={
            "profile": body.profile,
            "volume_path": body.volume_path,
            "total_documents": result.get("total_documents"),
        },
    )

    return APIResponse(status="success", data=result)


# --------------------------------------------------------------------------
# GET /status/{run_id}
# --------------------------------------------------------------------------
@router.get(
    "/status/{run_id}",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def extraction_status(run_id: str):
    """Fetch current job status with progress counters."""
    status = await extraction_engine.get_status(run_id)
    if not status:
        raise HTTPException(status_code=404, detail="Run not found")
    return APIResponse(status="success", data=status)


# --------------------------------------------------------------------------
# GET /stream/{run_id}  (SSE)
# --------------------------------------------------------------------------
@router.get(
    "/stream/{run_id}",
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def extraction_stream(run_id: str, request: Request):
    """Server-Sent Events stream for real-time extraction progress.

    Supports Last-Event-ID header for reconnection (replays missed events).
    If client disconnected > 5 min, falls back to full status poll.
    """
    last_event_id = request.headers.get("Last-Event-ID")

    async def _event_generator():
        seen_event_id = last_event_id
        poll_interval = 2  # seconds
        idle_count = 0
        max_idle = 150  # 5 min at 2s intervals

        while True:
            # Check if client disconnected
            if await request.is_disconnected():
                break

            events = await job_tracker.get_events(
                run_id, after_event_id=seen_event_id, limit=50
            )

            if events:
                idle_count = 0
                for event in events:
                    event_id = event.get("event_id", "")
                    event_type = event.get("event_type", "progress")
                    data = json.dumps(event, default=str)
                    yield f"id: {event_id}\nevent: {event_type}\ndata: {data}\n\n"
                    seen_event_id = event_id

                    # Close stream on terminal events
                    if event_type in ("JOB_COMPLETED", "JOB_COMPLETED_WITH_ERRORS",
                                      "JOB_FAILED", "JOB_CANCELLED"):
                        return
            else:
                idle_count += 1
                if idle_count > max_idle:
                    yield f"event: timeout\ndata: {{\"message\": \"Stream timed out\"}}\n\n"
                    return

            await asyncio.sleep(poll_interval)

    return StreamingResponse(
        _event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# --------------------------------------------------------------------------
# POST /cancel/{run_id}
# --------------------------------------------------------------------------
@router.post(
    "/cancel/{run_id}",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.OPERATOR))],
)
async def cancel_extraction(run_id: str, request: Request):
    """Cancel a running extraction job."""
    try:
        await extraction_engine.cancel(run_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    return APIResponse(status="success", data={"run_id": run_id, "state": "CANCELLED"})


# --------------------------------------------------------------------------
# POST /retry/{run_id}
# --------------------------------------------------------------------------
@router.post(
    "/retry/{run_id}",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.OPERATOR))],
)
async def retry_extraction(run_id: str, request: Request):
    """Retry only the failed documents from a previous run."""
    user_id = getattr(request.state, "user_id", "anonymous")
    try:
        result = await extraction_engine.retry_failed(run_id, created_by=user_id)
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return APIResponse(status="success", data=result)


# --------------------------------------------------------------------------
# GET /history
# --------------------------------------------------------------------------
@router.get(
    "/history",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def extraction_history(
    cursor: Optional[str] = None,
    limit: int = 20,
):
    """Paginated extraction job history."""
    jobs, next_cursor = await extraction_engine.get_history(
        cursor=cursor, limit=min(limit, 100)
    )
    return APIResponse(
        status="success",
        data={"jobs": jobs},
        meta={
            "pagination": PaginationMeta(
                next_cursor=next_cursor,
                has_more=next_cursor is not None,
            ).model_dump()
        },
    )
