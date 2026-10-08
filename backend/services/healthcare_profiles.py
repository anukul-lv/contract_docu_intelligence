"""Healthcare extraction profiles — 5 profiles mapping to ai_extract JSON schemas.

Profiles are immutable per extraction run. A snapshot is stored in
ingestion_jobs.profile_snapshot at submission time.
"""
import copy
import json
from typing import Any

# ---------------------------------------------------------------------------
# Base fields shared across all healthcare profiles
# ---------------------------------------------------------------------------
_BASE_FIELDS: dict[str, Any] = {
    "contract_type": {"type": "string", "description": "Type of healthcare contract"},
    "parties": {
        "type": "array",
        "items": {
            "type": "object",
            "properties": {
                "name": {"type": "string"},
                "role": {"type": "string", "description": "payer, provider, intermediary, other"},
                "npi": {"type": "string", "description": "National Provider Identifier (10 digits)"},
                "tax_id": {"type": "string"},
            },
        },
        "description": "All contracting parties",
    },
    "state_jurisdiction": {"type": "string", "description": "US state governing the contract"},
    "effective_date": {"type": "string", "format": "date"},
    "expiration_date": {"type": "string", "format": "date"},
    "term_months": {"type": "integer"},
    "auto_renewal": {"type": "boolean"},
    "auto_renewal_terms": {"type": "string"},
    "termination_notice_days": {"type": "integer"},
    "governing_law": {"type": "string"},
    "regulatory_tags": {"type": "array", "items": {"type": "string"}},
    "cms_regulatory_refs": {"type": "array", "items": {"type": "string"}},
    "baa_terms": {"type": "string", "description": "Business Associate Agreement terms"},
    "extracted_dates": {
        "type": "array",
        "items": {"type": "object", "properties": {"label": {"type": "string"}, "date": {"type": "string", "format": "date"}}},
    },
}

# ---------------------------------------------------------------------------
# Provider Agreement fields (physician, hospital, ancillary)
# ---------------------------------------------------------------------------
_PROVIDER_FIELDS: dict[str, Any] = {
    "reimbursement_method": {"type": "string", "description": "fee-for-service, capitation, case-rate, per-diem, DRG, value-based"},
    "fee_schedule": {"type": "string", "description": "Fee schedule reference or embedded schedule"},
    "drg_terms": {"type": "string", "description": "DRG-based payment terms and base rates"},
    "per_diem_rates": {"type": "string", "description": "Per-diem rate schedule"},
    "capitation_rates": {"type": "string", "description": "PMPM capitation rates"},
    "stop_loss_terms": {"type": "string", "description": "Stop-loss / reinsurance thresholds"},
    "quality_metrics": {"type": "string", "description": "Quality metrics and performance targets"},
    "shared_savings": {"type": "string", "description": "Shared savings / gainsharing terms"},
    "credentialing": {"type": "string", "description": "Credentialing and recredentialing requirements"},
    "network_adequacy": {"type": "string", "description": "Network adequacy standards"},
    "delegated_functions": {"type": "string", "description": "Delegated functions (UM, credentialing, claims)"},
}

# ---------------------------------------------------------------------------
# Hospital / Facility fields
# ---------------------------------------------------------------------------
_HOSPITAL_FIELDS: dict[str, Any] = {
    **_PROVIDER_FIELDS,
    "drg_terms": {"type": "string", "description": "DRG base rate, outlier threshold, transfer policy, carve-outs, case rates"},
}

# ---------------------------------------------------------------------------
# Government Program fields (Medicare Advantage, Medicaid)
# ---------------------------------------------------------------------------
_GOVT_FIELDS: dict[str, Any] = {
    **_PROVIDER_FIELDS,
    "cms_contract_id": {"type": "string", "description": "CMS contract identifier (H-number or similar)"},
    "eligibility_categories": {"type": "string", "description": "Covered eligibility categories"},
    "mlr_terms": {"type": "string", "description": "Medical Loss Ratio requirements"},
    "risk_adjustment": {"type": "string", "description": "Risk adjustment methodology"},
    "star_rating_terms": {"type": "string", "description": "Star rating performance thresholds"},
}


# =========================================================================
# Profile Registry
# =========================================================================

def _build_schema(name: str, description: str, extra_fields: dict[str, Any]) -> dict:
    """Build a complete JSON schema for ai_extract from base + extra fields."""
    properties = {**_BASE_FIELDS, **extra_fields}
    return {
        "name": name,
        "description": description,
        "type": "object",
        "properties": properties,
    }


PROFILES: dict[str, dict] = {
    "general_healthcare": _build_schema(
        "general_healthcare",
        "General healthcare contract — parties, dates, terms, governing law",
        {},
    ),
    "provider_agreement": _build_schema(
        "provider_agreement",
        "Physician / hospital / ancillary provider agreement — reimbursement, fees, credentialing",
        _PROVIDER_FIELDS,
    ),
    "hospital_facility": _build_schema(
        "hospital_facility",
        "Hospital / facility contract — DRG base rate, outlier, transfer policy, carve-outs",
        _HOSPITAL_FIELDS,
    ),
    "government_program": _build_schema(
        "government_program",
        "Medicare Advantage / Medicaid managed care — CMS IDs, MLR, risk adjustment, star ratings",
        _GOVT_FIELDS,
    ),
    "custom_json": None,  # User-provided schema at runtime
}


def get_profile(profile_name: str, custom_schema: dict | None = None) -> dict:
    """Return the extraction schema for a given profile name.

    Raises ValueError if the profile is unknown or custom_json is used
    without providing a schema.
    """
    if profile_name == "custom_json":
        if not custom_schema:
            raise ValueError("custom_json profile requires a user-provided JSON schema")
        return custom_schema

    schema = PROFILES.get(profile_name)
    if schema is None:
        raise ValueError(
            f"Unknown profile '{profile_name}'. "
            f"Available: {', '.join(PROFILES.keys())}"
        )
    return copy.deepcopy(schema)


def get_profile_snapshot(profile_name: str, custom_schema: dict | None = None) -> str:
    """Return a JSON-serialized immutable snapshot for storage in ingestion_jobs."""
    return json.dumps(get_profile(profile_name, custom_schema), default=str)


def list_profiles() -> list[dict]:
    """Return summary info for all available profiles."""
    return [
        {"name": name, "description": (schema or {}).get("description", "User-provided schema")}
        for name, schema in PROFILES.items()
    ]
