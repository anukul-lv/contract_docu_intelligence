"""4-signal weighted confidence model for extracted fields.

Signals and weights:
  ai_extract native confidence  50%  — built-in per-field score (0.0–1.0)
  OCR quality of source page     20%  — ai_parse_document quality metrics
  Value format validation        20%  — regex: dates, currency, NPI, etc.
  Cross-field consistency        10%  — effective < expiration, PMPM > 0, etc.
"""
import logging
import re
from datetime import datetime
from typing import Any

logger = logging.getLogger("healthcontracts")

# ---------------------------------------------------------------------------
# Weights
# ---------------------------------------------------------------------------
W_AI_CONF = 0.50
W_OCR = 0.20
W_FORMAT = 0.20
W_CROSS = 0.10


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def compute_confidence(
    ai_conf: float,
    ocr_quality: float,
    format_valid: bool,
    cross_field_valid: bool,
) -> float:
    """Compute the weighted confidence score for a single field."""
    return round(
        W_AI_CONF * _clamp(ai_conf)
        + W_OCR * _clamp(ocr_quality)
        + W_FORMAT * (1.0 if format_valid else 0.3)
        + W_CROSS * (1.0 if cross_field_valid else 0.2),
        4,
    )


def compute_confidence_explanation(
    ai_conf: float,
    ocr_quality: float,
    format_valid: bool,
    cross_field_valid: bool,
) -> dict:
    """Return a human-readable breakdown alongside the final score."""
    score = compute_confidence(ai_conf, ocr_quality, format_valid, cross_field_valid)
    return {
        "final_score": score,
        "signals": {
            "ai_extract_confidence": {"value": round(ai_conf, 4), "weight": W_AI_CONF},
            "ocr_quality": {"value": round(ocr_quality, 4), "weight": W_OCR},
            "format_validation": {"value": format_valid, "weight": W_FORMAT},
            "cross_field_consistency": {"value": cross_field_valid, "weight": W_CROSS},
        },
    }


def score_all_fields(
    extraction_result: dict[str, Any],
    ocr_quality: float,
    field_confidences: dict[str, float] | None = None,
) -> dict[str, dict]:
    """Score every extracted field and return {field_name: explanation}.

    Args:
        extraction_result: The dict output from ai_extract.
        ocr_quality: Page-level OCR quality (0.0–1.0).
        field_confidences: Per-field ai_extract confidence scores (optional).
    """
    field_confidences = field_confidences or {}
    scores: dict[str, dict] = {}

    for field_name, value in extraction_result.items():
        if field_name.startswith("_") or value is None:
            continue
        ai_conf = field_confidences.get(field_name, 0.5)  # default mid-range
        fmt_valid = validate_format(field_name, value)
        cross_valid = validate_cross_field(field_name, value, extraction_result)
        scores[field_name] = compute_confidence_explanation(
            ai_conf, ocr_quality, fmt_valid, cross_valid
        )
    return scores


# ---------------------------------------------------------------------------
# Format validation helpers
# ---------------------------------------------------------------------------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_CURRENCY_RE = re.compile(r"^\$?[\d,]+(\.[\d]{1,2})?$")
_NPI_RE = re.compile(r"^\d{10}$")
_MEDICARE_RE = re.compile(r"^\d{11}$")


def validate_format(field_name: str, value: Any) -> bool:
    """Return True if the value matches expected format for the field type."""
    val_str = str(value).strip() if value is not None else ""
    if not val_str:
        return False

    fn = field_name.lower()
    if fn.endswith("_date") or fn in ("effective_date", "expiration_date"):
        return bool(_DATE_RE.match(val_str))
    if any(kw in fn for kw in ("rate", "pmpm", "cost", "fee", "amount", "price")):
        return bool(_CURRENCY_RE.match(val_str.replace("$", "").replace(",", "")))
    if "npi" in fn:
        return bool(_NPI_RE.match(val_str))
    if "medicare_id" in fn:
        return bool(_MEDICARE_RE.match(val_str))
    # Default: non-empty string is valid
    return True


def validate_cross_field(field_name: str, value: Any, full_result: dict) -> bool:
    """Check cross-field consistency rules."""
    fn = field_name.lower()

    # effective_date should be before expiration_date
    if fn == "effective_date":
        exp = full_result.get("expiration_date")
        if exp and value:
            try:
                return datetime.fromisoformat(str(value)) < datetime.fromisoformat(str(exp))
            except (ValueError, TypeError):
                return False

    # PMPM / capitation rates should be positive
    if any(kw in fn for kw in ("pmpm", "capitation", "per_diem")):
        try:
            return float(str(value).replace("$", "").replace(",", "")) > 0
        except (ValueError, TypeError):
            return False

    # Parties should not be empty
    if fn == "parties":
        return isinstance(value, (list, str)) and len(value) > 0

    # term_months should be positive
    if fn == "term_months":
        try:
            return int(value) > 0
        except (ValueError, TypeError):
            return False

    return True


# ---------------------------------------------------------------------------
# Review routing
# ---------------------------------------------------------------------------

def should_route_to_review(
    field_name: str,
    field_class: str,
    confidence: float,
    thresholds: dict[str, dict],
) -> bool:
    """Determine whether a field should be routed to the review queue.

    Args:
        field_name: The extracted field name.
        field_class: One of critical_financial, critical_compliance,
                     important_structural, low_risk_metadata.
        confidence: The composite confidence score.
        thresholds: Loaded from confidence_thresholds table.
    """
    rules = thresholds.get(field_class, {})
    if rules.get("always_review", False):
        return True
    review_threshold = float(rules.get("auto_approve_threshold", 0.92))
    return confidence < review_threshold


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _clamp(v: float, lo: float = 0.0, hi: float = 1.0) -> float:
    return max(lo, min(hi, v))
