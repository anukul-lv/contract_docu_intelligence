# Healthcare Extraction Profiles

5 built-in profiles, each mapping to an `ai_extract` JSON schema. Profiles are immutable per extraction run — a snapshot is stored in `ingestion_jobs.profile_snapshot`.

## 1. General Healthcare
For any healthcare contract. Extracts: parties, dates, terms, governing law, regulatory tags.

## 2. Provider Agreement
Physician, hospital, and ancillary provider contracts. Adds: reimbursement method, fee schedule, DRG terms, per-diem rates, capitation rates, stop-loss, credentialing, network adequacy, delegated functions.

## 3. Hospital / Facility
Hospital-specific contracts. Extends Provider Agreement with: DRG base rate, outlier threshold, transfer policy, carve-outs, case rates.

## 4. Government Program
Medicare Advantage and Medicaid managed care. Adds: CMS contract ID, eligibility categories, MLR terms, risk adjustment, star rating terms.

## 5. Custom JSON
User-provided JSON schema. Submit any valid JSON schema at extraction time via the `custom_schema` field in the API request.

## Selecting a Profile

- The system auto-detects document category via `ai_classify` (10 categories)
- If classified as Provider Agreement or Hospital, the corresponding profile is suggested
- Government programs (MA, Medicaid) use the Government Program profile
- BAAs and other types default to General Healthcare
- Users can override the auto-selected profile

## Profile Immutability

Profiles are **immutable per extraction run**. When extraction starts, a full snapshot of the selected profile is stored in the `ingestion_jobs.profile_snapshot` VARIANT column. This guarantees reproducibility — even if the profile definition is updated later, past extraction results can always be explained.

## Field Classes

Each extracted field is assigned a class that controls review routing:

| Field Class | Description | Auto-Approve? |
|-------------|-------------|---------------|
| `critical_financial` | Payment terms, rates, reimbursement amounts | Never — always requires human review |
| `critical_compliance` | Regulatory terms, HIPAA clauses, governing law | Never — always requires human review |
| `important_structural` | Dates, parties, term length, renewal terms | Auto-approve above 0.92 confidence |
| `low_risk_metadata` | Contract type, document ID, page count | Auto-approve above 0.85 confidence |

## Custom JSON Schema

To use a custom profile, provide a JSON schema in the extraction API:

```json
{
  "profile": "custom_json",
  "custom_schema": {
    "fields": [
      {"name": "penalty_clause", "type": "string", "class": "critical_financial"},
      {"name": "arbitration_venue", "type": "string", "class": "important_structural"}
    ]
  }
}
```

Custom schemas support the same field classes and confidence scoring as built-in profiles.

## API

List available profiles: `GET /api/v1/settings/profiles`

Get snapshot of a specific run's profile: included in `GET /api/v1/extract/status/{run_id}`
