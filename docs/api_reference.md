# API Reference

Complete REST API documentation for HealthContracts AI R1.

## Base URL

```
https://<app-host>/api/v1
```

## Authentication

All requests are authenticated via Databricks App proxy headers:
- `X-Forwarded-Email` — User email
- `X-Forwarded-Preferred-Username` — Username
- `X-Forwarded-Groups` — Databricks groups (mapped to roles)

### Roles
| Group | Role | Access |
|-------|------|--------|
| `healthcare_admin` | ADMIN | Full access |
| `healthcare_reviewer` | REVIEWER | Review + read |
| `healthcare_operator` | OPERATOR | Upload + extract + read |
| `healthcare_viewer` | VIEWER | Read-only |

---

## Health

### `GET /api/health`
Returns component status. No auth required.

---

## Documents (R1_04)

### `POST /api/v1/documents/upload`
Upload a document. **Requires OPERATOR.**
- Multipart file upload. Max 500MB.
- Allowed: `.pdf, .docx, .pptx, .png, .tiff, .tif`

### `GET /api/v1/documents/list`
List uploaded documents. **Requires VIEWER.**
- Query: `?cursor=&limit=50`

### `GET /api/v1/documents/preview/{document_version_id}`
Preview a document. **Requires VIEWER.**

### `POST /api/v1/documents/dedupe-check`
Check for duplicate uploads. **Requires OPERATOR.**
- Body: `{ "checksums": ["..."] }`

---

## Extraction (R1_05)

### `POST /api/v1/extract/start`
Submit extraction job. **Requires OPERATOR.**
- Body: `ExtractionStartRequest` (volume_path, profile, output_catalog, output_schema, idempotency_key)
- Returns: `{ run_id, state, estimated_duration_min, estimated_cost }`

### `GET /api/v1/extract/status/{run_id}`
Job status with progress. **Requires VIEWER.**

### `GET /api/v1/extract/stream/{run_id}`
SSE stream for real-time progress. Supports `Last-Event-ID` reconnection. **Requires VIEWER.**

### `POST /api/v1/extract/cancel/{run_id}`
Cancel running job. **Requires OPERATOR.**

### `POST /api/v1/extract/retry/{run_id}`
Retry failed documents. **Requires OPERATOR.**

### `GET /api/v1/extract/history`
Paginated job history. **Requires VIEWER.**
- Query: `?cursor=&limit=20`

---

## Review (R1_06)

### `GET /api/v1/review/queue`
Paginated review queue. **Requires VIEWER.**
- Query: `?cursor=&limit=50&status=PENDING&priority=&assigned_to=&field_class=`

### `POST /api/v1/review/{review_id}/claim`
Claim item (optimistic lock). **Requires REVIEWER.**
- Body: `{ "expected_version": 1 }`
- Returns 409 on version conflict.

### `POST /api/v1/review/{review_id}/approve`
Approve item. **Requires REVIEWER.**
- Body: `{ "expected_version": 2, "comment": "..." }`

### `POST /api/v1/review/{review_id}/correct`
Correct with new value. **Requires REVIEWER.**
- Body: `{ "expected_version": 2, "corrected_value": "...", "correction_reason": "...", "comment": "..." }`

### `POST /api/v1/review/{review_id}/flag`
Flag for attention. **Requires REVIEWER.**
- Body: `{ "expected_version": 2, "reason": "..." }`

### `POST /api/v1/review/batch-approve`
Batch approve non-critical fields. **Requires REVIEWER.**
- Body: `{ "review_ids": [...], "min_confidence": 0.85 }`
- Excludes `critical_financial` and `critical_compliance` fields.

### `POST /api/v1/review/{review_id}/revert`
Revert to AI value. **Requires REVIEWER.**
- Body: `{ "reason": "..." }`

### `GET /api/v1/review/stats`
Review dashboard stats. **Requires VIEWER.**

---

## Explorer (R1_07)

### `GET /api/v1/explorer/contracts`
Paginated contract list with filters. **Requires VIEWER.**
- Query: `?cursor=&limit=25&contract_type=&state=&status=&reimbursement_method=&date_from=&date_to=&min_confidence=&max_confidence=`

### `GET /api/v1/explorer/contracts/{family_id}`
Contract detail with all fields and trust badges. **Requires VIEWER.**

### `GET /api/v1/explorer/filters`
Distinct values for filter dropdowns. **Requires VIEWER.**

### `GET /api/v1/explorer/dashboard`
Pre-aggregated dashboard widget data. **Requires VIEWER.**

---

## Settings (R1_08)

### `GET /api/v1/settings`
Current app settings. **Requires VIEWER.**

### `PUT /api/v1/settings`
Update settings. **Requires ADMIN.**

### `GET /api/v1/settings/flags`
All feature flags. **Requires VIEWER.**

### `PUT /api/v1/settings/flags/{flag_name}`
Toggle feature flag. **Requires ADMIN.** Invalidates cache immediately.

### `GET /api/v1/settings/profiles`
List extraction profiles. **Requires VIEWER.**

---

## Admin (R1_08)

### `GET /api/v1/admin/audit-log`
Paginated HIPAA audit log. **Requires ADMIN.**
- Query: `?cursor=&limit=100&user=&event_type=&date_from=&date_to=`

### `GET /api/v1/admin/audit-log/event-types`
Distinct event types for filter dropdown. **Requires ADMIN.**

---

## Response Envelope

All endpoints return a consistent JSON envelope:

```json
{
  "status": "success",
  "data": { ... },
  "meta": {
    "pagination": {
      "next_cursor": "...",
      "has_more": true,
      "total_count": 150
    }
  }
}
```

On error:

```json
{
  "status": "error",
  "error": "Human-readable error message",
  "detail": "Technical detail for debugging"
}
```

## HTTP Status Codes

| Code | Meaning |
|------|---------|
| 200 | Success |
| 400 | Bad request (invalid input) |
| 403 | Forbidden (insufficient role) |
| 404 | Resource not found |
| 409 | Conflict (version mismatch on review actions) |
| 422 | Validation error (missing required fields) |
| 500 | Internal server error |
| 503 | Service unavailable (warehouse cold start, job submission failure) |

## Pagination

All list endpoints use **cursor-based pagination**:
- Pass `?cursor=<next_cursor>` to get the next page
- `has_more: true` indicates more results are available
- Cursors are opaque Base64-encoded composite keys (do not parse or construct them)
