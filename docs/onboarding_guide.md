# Onboarding Guide

Getting started with HealthContracts AI — the Databricks-native platform for healthcare contract intelligence.

## Prerequisites

- Databricks workspace with Unity Catalog enabled
- Access to the `dev.doc_intel` catalog and schema
- Membership in one of: `healthcare_admin`, `healthcare_reviewer`, `healthcare_operator`, `healthcare_viewer`
- SQL warehouse available (serverless recommended)

## Quick Start

1. Open the HealthContracts AI app from your Databricks workspace.
2. You land on the **Ingest** tab (first visit) or **Explore** (returning user with data).
3. If this is your first time, click **Try Sample Data** to load 10 synthetic healthcare contracts.

## First Extraction Walkthrough

### Step 1: Upload Documents

Navigate to the **Ingest** tab. You can:
- **Drag and drop** PDF files into the upload zone
- **Browse** to select files from your computer
- **Connect a Volume** — enter Catalog, Schema, and Volume to ingest from a Unity Catalog volume

Supported formats: PDF (max 500 MB per file).

### Step 2: Choose an Extraction Profile

Select one of 5 built-in profiles:

| Profile | Use Case |
|---------|----------|
| General Healthcare | Broad contract extraction — works for most documents |
| Provider Agreement | Physician fee schedules, credentialing |
| Hospital / Facility | DRG, per diem, multi-methodology |
| Government Program | Medicare/Medicaid, PMPM rates, risk adjustment |
| Custom JSON | Provide your own extraction schema |

See [Healthcare Profiles](healthcare_profiles.md) for details.

### Step 3: Start Extraction

Click **Start Extraction**. The system:
1. Submits a Lakeflow Job for batch processing
2. Parses each PDF with `ai_parse_document`
3. Classifies the contract type with `ai_classify`
4. Extracts structured fields per the selected profile
5. Scans for PHI (if healthcare mode is enabled)
6. Chunks documents for future search

Real-time progress streams via SSE (Server-Sent Events). Cost estimates are shown before and during the run.

### Step 4: Review Results

Navigate to the **Review** tab. The review queue shows:
- Fields routed for human review (critical_financial, critical_compliance, and low-confidence fields)
- Confidence scores with 4-signal breakdown
- Source citations linking back to the original document

**Actions**: Approve, Correct, or Flag each field. Batch approve is available for non-critical fields above the confidence threshold.

**Keyboard shortcuts**: Press `?` on the Review page to see all shortcuts (A=Approve, C=Correct, F=Flag, N=Next, P=Previous).

### Step 5: Explore Contracts

Navigate to the **Explore** tab. Browse all contracts with:
- Search by keyword
- Filter by contract type, state, status
- Card view with confidence scores and trust badges
- Detail view grouping fields by class with trust indicators

**Trust Badges**:
- 🟢 **Verified** — Human-approved
- 🟡 **AI Extracted** — Above confidence threshold, not yet reviewed
- 🔵 **Corrected** — Human corrected the AI value
- 🔴 **Flagged** — Marked for escalation
- 🟠 **Low Confidence** — Below auto-approve threshold
- 🟣 **Anomaly** — Statistical outlier (3-sigma)

## Roles & Permissions

| Role | Upload | Extract | Review | Admin | View |
|------|--------|---------|--------|-------|------|
| ADMIN | ✅ | ✅ | ✅ | ✅ | ✅ |
| REVIEWER | ❌ | ❌ | ✅ | ❌ | ✅ |
| OPERATOR | ✅ | ✅ | ❌ | ❌ | ✅ |
| VIEWER | ❌ | ❌ | ❌ | ❌ | ✅ |

## Getting Help

- Press **?** in the app header for contextual help
- See [API Reference](api_reference.md) for backend endpoints
- See [Developer Guide](developer_guide.md) for local development setup
- See [HIPAA Compliance](hipaa_compliance.md) for security and audit information
