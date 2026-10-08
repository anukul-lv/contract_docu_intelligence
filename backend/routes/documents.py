"""Document intake API — upload, list, preview, dedupe-check.

Endpoints:
    POST /api/v1/documents/upload         — Streaming multipart upload (max 500 MB)
    GET  /api/v1/documents/list            — Cursor-paginated file listing
    GET  /api/v1/documents/preview/{id}    — First-page preview + metadata
    POST /api/v1/documents/dedupe-check    — Checksum duplicate detection
"""
import base64
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, File

from backend.middleware.auth import require_role
from backend.models.domain import UserRole
from backend.models.requests import DedupeCheckRequest
from backend.models.responses import APIResponse, PaginationMeta
from backend.services.dedup_service import dedup_service
from backend.services.document_upload import upload_service
from backend.services.hipaa_audit import audit_service
from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")
router = APIRouter(prefix="/v1/documents", tags=["documents"])


# --------------------------------------------------------------------------
# POST /upload
# --------------------------------------------------------------------------
@router.post(
    "/upload",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.OPERATOR))],
)
async def upload_documents(
    request: Request,
    files: list[UploadFile] = File(...),
):
    """Stream one or more files to UC Volume.

    * Validates extension and 500 MB size limit per file.
    * Computes MD5 checksum during streaming.
    * Writes HIPAA audit entry for every upload.
    """
    user_id = getattr(request.state, "user_id", "anonymous")
    results = []
    errors = []

    for upload_file in files:
        try:
            # Build an async chunk iterator
            async def _stream(uf=upload_file):
                while True:
                    chunk = await uf.read(upload_service.CHUNK_SIZE)
                    if not chunk:
                        break
                    yield chunk

            metadata = await upload_service.upload_file(
                file_name=upload_file.filename or "unnamed",
                file_stream=_stream(),
                content_length=upload_file.size,
            )
            results.append(metadata)

            # HIPAA audit
            await audit_service.log_event(
                event_type="DOCUMENT_UPLOAD",
                user_identity=user_id,
                user_role=getattr(request.state, "user_role", UserRole.VIEWER).value,
                resource_type="document",
                resource_id=metadata["file_id"],
                action="upload",
                details={
                    "file_name": metadata["file_name"],
                    "file_size_bytes": metadata["file_size_bytes"],
                    "checksum": metadata["checksum"],
                },
            )

        except ValueError as exc:
            errors.append({"file": upload_file.filename, "error": str(exc)})
        except Exception as exc:
            logger.error("Upload failed for %s: %s", upload_file.filename, exc)
            errors.append({"file": upload_file.filename, "error": "Upload failed"})

    if not results and errors:
        raise HTTPException(status_code=400, detail=errors)

    settings = get_settings()
    return APIResponse(
        status="success",
        data={
            "file_ids": [r["file_id"] for r in results],
            "files": results,
            "volume_path": f"/Volumes/{settings.customer_catalog}/{settings.customer_schema}/prvdr_contracts/uploads/",
            "errors": errors or None,
        },
    )


# --------------------------------------------------------------------------
# GET /list
# --------------------------------------------------------------------------
@router.get(
    "/list",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def list_documents(
    cursor: Optional[str] = None,
    limit: int = 50,
    file_type: Optional[str] = None,
    status: Optional[str] = None,
):
    """Cursor-paginated document listing from contracts_parsed."""
    settings = get_settings()
    limit = min(limit, 200)  # cap

    # Decode cursor (base64-encoded extraction_ts of last item)
    where_clauses = []
    params: dict[str, str] = {}
    if cursor:
        try:
            decoded = base64.b64decode(cursor).decode()
            where_clauses.append("extraction_ts < TIMESTAMP :cursor_ts")
            params["cursor_ts"] = decoded
        except Exception:
            raise HTTPException(status_code=400, detail="Invalid cursor")
    if file_type:
        where_clauses.append("file_type = :file_type")
        params["file_type"] = file_type
    if status:
        where_clauses.append("verification_status = :status")
        params["status"] = status

    where_sql = ("WHERE " + " AND ".join(where_clauses)) if where_clauses else ""

    # Fetch one extra row to determine has_more
    rows = await execute_sql(
        f"""
        SELECT document_version_id, source_document_id, file_name, file_path,
               file_size_bytes, file_type, extraction_ts, verification_status,
               extraction_profile, quality_score
        FROM {settings.customer_catalog}.{settings.customer_schema}.contracts_parsed
        {where_sql}
        ORDER BY extraction_ts DESC
        LIMIT {limit + 1}
        """,
        parameters=params if params else None,
    )

    has_more = len(rows) > limit
    documents = rows[:limit]

    next_cursor = None
    if has_more and documents:
        last_ts = documents[-1].get("extraction_ts", "")
        next_cursor = base64.b64encode(str(last_ts).encode()).decode()

    # Total count (cached/approximate for performance)
    count_rows = await execute_sql(
        f"SELECT COUNT(*) as cnt FROM {settings.customer_catalog}.{settings.customer_schema}.contracts_parsed"
    )
    total_count = int(count_rows[0]["cnt"]) if count_rows else 0

    return APIResponse(
        status="success",
        data={"documents": documents},
        meta={
            "pagination": PaginationMeta(
                next_cursor=next_cursor,
                has_more=has_more,
                total_count=total_count,
            ).model_dump()
        },
    )


# --------------------------------------------------------------------------
# GET /preview/{document_version_id}
# --------------------------------------------------------------------------
@router.get(
    "/preview/{document_version_id}",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.VIEWER))],
)
async def preview_document(document_version_id: str):
    """Return first-page preview and metadata for a document."""
    settings = get_settings()

    rows = await execute_sql(
        f"""
        SELECT document_version_id, file_name, file_type, file_path,
               page_count, file_size_bytes, extraction_ts, extraction_profile,
               quality_score, verification_status, contract_type, parties,
               effective_date, expiration_date, executive_summary
        FROM {settings.customer_catalog}.{settings.customer_schema}.contracts_parsed
        WHERE document_version_id = :doc_id
        LIMIT 1
        """,
        parameters={"doc_id": document_version_id},
    )

    if not rows:
        raise HTTPException(status_code=404, detail="Document not found")

    doc = rows[0]
    return APIResponse(
        status="success",
        data={
            "document_version_id": doc["document_version_id"],
            "file_name": doc.get("file_name"),
            "file_type": doc.get("file_type"),
            "page_count": doc.get("page_count"),
            "file_size_bytes": doc.get("file_size_bytes"),
            "preview_url": None,  # Generated on demand by frontend via Files API
            "metadata": {
                "extraction_ts": doc.get("extraction_ts"),
                "extraction_profile": doc.get("extraction_profile"),
                "quality_score": doc.get("quality_score"),
                "verification_status": doc.get("verification_status"),
                "contract_type": doc.get("contract_type"),
                "parties": doc.get("parties"),
                "effective_date": doc.get("effective_date"),
                "expiration_date": doc.get("expiration_date"),
                "executive_summary": doc.get("executive_summary"),
            },
        },
    )


# --------------------------------------------------------------------------
# POST /dedupe-check
# --------------------------------------------------------------------------
@router.post(
    "/dedupe-check",
    response_model=APIResponse,
    dependencies=[Depends(require_role(UserRole.OPERATOR))],
)
async def dedupe_check(body: DedupeCheckRequest):
    """Check file checksums against existing documents for duplicates."""
    duplicates = await dedup_service.check_checksums(body.file_checksums)
    return APIResponse(
        status="success",
        data={"duplicates": duplicates},
    )
