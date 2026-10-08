# HIPAA Compliance

PHI handling, audit logging, and retention policies for HealthContracts AI.

## Audit Log
- Every API request (except `/health`) is logged to `hipaa_audit_log` table
- Change Data Feed (CDF) enabled for tamper detection
- 7-year retention (`delta.deletedFileRetentionDuration = interval 2555 days`)
- Fields: event_ts, event_type, user_identity, user_role, resource_type, resource_id, action, phi_accessed, ip_address

## PHI Detection
3-layer detection system:
1. **ai_mask**: Standard PII (names, SSN, addresses)
2. **Healthcare regex**: Medicare IDs, Medicaid IDs, MRNs, DOB, NPI, phone, email
3. **Deep ai_extract scan**: Clinical/member-sensitive context

## PHI Storage
- PHI findings stored in `phi_vault` table with 7-year retention
- Original values masked (first/last character preserved, middle replaced with `*`)
- `phi_detected` flag set on `contracts_parsed` for affected documents

## Data Retention
| Table | Retention | Reason |
|-------|-----------|--------|
| hipaa_audit_log | 7 years (2555 days) | HIPAA requirement |
| phi_vault | 7 years (2555 days) | HIPAA requirement |
| contracts_parsed | Standard (via VACUUM) | Business data |
| contracts_current | Standard (via VACUUM) | Business data |

## Access Controls

- Role-based access via Databricks group membership (4 roles: Admin, Reviewer, Operator, Viewer)
- Admin-only access to audit log viewer and settings
- All PHI access events logged with `phi_accessed = true` and `phi_fields_accessed` array
- Security headers on every response: CSP, HSTS, X-Frame-Options, X-Content-Type-Options, X-XSS-Protection

## PHI Detection Patterns (8 types)

| Pattern | Regex | Example |
|---------|-------|---------|
| MEDICARE_ID | `\b[1-9][A-Z][A-Z0-9]\d{4}[A-Z]{2}\d{2}\b` | 1AB1234CD56 |
| MEDICAID_ID | `\b\d{10,12}\b` (in Medicaid context) | 1234567890 |
| MRN | `\bMRN[:\s]*\d{6,10}\b` | MRN: 12345678 |
| SSN | `\b\d{3}-\d{2}-\d{4}\b` | 123-45-6789 |
| DOB | `\b(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/(19|20)\d{2}\b` | 01/15/1990 |
| NPI | `\b\d{10}\b` (in NPI context) | 1234567890 |
| PHONE | `\b\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}\b` | (555) 123-4567 |
| EMAIL | `\b[\w.-]+@[\w.-]+\.\w+\b` | patient@email.com |

## Audit Event Types

| Event Type | When Logged |
|------------|-------------|
| DOCUMENT_UPLOADED | File uploaded via API |
| EXTRACTION_STARTED | Extraction job submitted |
| EXTRACTION_COMPLETED | Extraction job finished |
| REVIEW_CLAIMED | Review item claimed by reviewer |
| REVIEW_APPROVED | Field approved |
| REVIEW_CORRECTED | Field corrected |
| REVIEW_FLAGGED | Field flagged |
| REVIEW_REVERTED | Approved/corrected field reverted |
| BATCH_APPROVED | Batch approve executed |
| PHI_DETECTED | PHI found in document |
| PHI_ACCESSED | User accessed PHI data |
| SETTINGS_UPDATED | Admin changed settings |
| FLAG_UPDATED | Admin toggled feature flag |
| LOGIN | User authenticated |

## Incident Response

If a PHI breach is suspected:
1. Query `hipaa_audit_log` for `phi_accessed = true` events
2. Filter by time window, user, and resource
3. Cross-reference with `phi_vault` for affected fields
4. Use Change Data Feed on audit log to verify no tampering
5. Export audit trail for compliance review

## Compliance Verification

```sql
-- Verify audit log retention
SHOW TBLPROPERTIES dev.doc_intel.hipaa_audit_log;
-- Should show: delta.deletedFileRetentionDuration = interval 2555 days

-- Count PHI access events in last 30 days
SELECT event_type, COUNT(*) AS cnt
FROM dev.doc_intel.hipaa_audit_log
WHERE phi_accessed = true
  AND event_timestamp >= current_timestamp() - INTERVAL 30 DAYS
GROUP BY event_type;
```
