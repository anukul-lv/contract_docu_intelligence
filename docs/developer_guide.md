# Developer Guide

Local development, testing, and deployment guide for HealthContracts AI.

## Project Structure
```
HealthContracts-AI/
  app.py                    # FastAPI entry point
  app.yaml                  # Databricks App config
  requirements.txt          # Python dependencies
  backend/
    config.py               # Settings (env-based)
    dependencies.py         # Shared deps (WorkspaceClient, execute_sql)
    middleware/              # Auth, security headers, timing, audit
    models/                  # Pydantic: domain, requests, responses
    routes/                  # API routers: documents, extraction, review, explorer, settings, admin
    services/               # Business logic: extraction engine, review, PHI, confidence, etc.
  notebooks/                # Lakeflow Job notebooks
  frontend/                 # React (Vite + TypeScript)
  tests/                    # unit/, integration/, e2e/
  bundles/                  # DABs deployment
  docs/                     # Documentation
```

## Local Development
```bash
pip install -r requirements.txt
uvicorn app:app --reload --port 8000
```

Required env vars: `APP_CATALOG`, `APP_SCHEMA`, `CUSTOMER_CATALOG`, `CUSTOMER_SCHEMA`, `VOLUME_PATH`

## Testing
```bash
# Unit tests
pytest tests/unit/ -v

# Integration tests (requires SQL warehouse access)
pytest tests/integration/ -v

# Coverage
pytest tests/unit/ --cov=backend --cov-report=html
```

## DABs Deployment
```bash
cd bundles/
databricks bundle deploy --target dev
```

## Key Patterns

- **Optimistic locking**: All review mutations use `MERGE ... ON version_number = expected` → 409 on conflict
- **Circuit breaker**: Wraps AI Gateway, SQL warehouse, AI Search calls
- **Feature flags**: `feature_flags` table + in-memory cache with 60s TTL async refresh
- **HIPAA audit**: Auto-logged via `AuditLoggerMiddleware` on all non-health endpoints
- **Immutable audit trail**: `review_actions` is append-only (never UPDATE/DELETE)
- **Cursor pagination**: All list endpoints use composite cursor (timestamp|id) encoded as Base64
- **SSE streaming**: Extraction progress uses Server-Sent Events with `Last-Event-ID` replay
- **Confidence scoring**: 4-signal weighted formula: AI confidence (50%) + format validation (20%) + cross-field validation (20%) + citation presence (10%)

## Frontend Development

```bash
cd frontend/
npm install
npm run dev        # Dev server on port 5173, proxies /api to :8000
npm run build      # Production build to ../static/
npm run test       # Vitest unit tests
npm run lint       # ESLint
```

Stack: React 18, TypeScript (strict), Vite, Zustand (3 stores), TanStack Query, Recharts, shadcn/ui (Radix), Tailwind CSS.

## E2E Testing

```bash
cd tests/e2e/
npx playwright install
npx playwright test
```

Critical path test: Upload → Extract → Review → Explore with axe-core accessibility checks at every page.

## Delta Tables (R1)

12 tables in `dev.doc_intel`:

| Table | Purpose |
|-------|---------|
| `feature_flags` | Feature flag configuration |
| `confidence_thresholds` | Per-field-class confidence thresholds |
| `guardrail_policy` | Guardrail and validation rules |
| `cost_tracking` | AI function cost tracking |
| `ingestion_jobs` | Extraction job metadata |
| `ingestion_job_events` | Per-document extraction events |
| `review_queue` | Review items with version_number |
| `review_actions` | Immutable review action history |
| `hipaa_audit_log` | HIPAA audit trail (7-year retention) |
| `phi_vault` | PHI findings (7-year retention) |
| `contracts_parsed` | Raw extraction results |
| `contracts_current` | Materialized current state view |

Bootstrap: `notebooks/bootstrap_tables.py` + `notebooks/bootstrap_grants.sql`

## Scheduled Jobs

| Job | Schedule | Purpose |
|-----|----------|---------|
| `optimize_vacuum_job.py` | Nightly 2 AM | OPTIMIZE + VACUUM all 12 tables |
| `current_state_rebuild.py` | Nightly 1 AM | Full MERGE rebuild of contracts_current |

## Adding a New Feature

1. Create a feature flag in `bootstrap_tables.py` (INSERT into `feature_flags`)
2. Guard your code with `flag_cache.is_enabled("your_flag")`
3. Add unit tests in `tests/unit/`
4. Add integration tests in `tests/integration/`
5. Update `api_reference.md` if adding new endpoints
6. Deploy with `databricks bundle deploy --target dev`
