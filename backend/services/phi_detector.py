"""Three-layer PHI detection service.

Layers:
  1. ai_mask — standard PII detection (names, SSN, addresses)
  2. Healthcare regex — Medicare IDs, Medicaid IDs, MRNs, DOB in context
  3. Deep ai_extract scan — clinical / member-sensitive context detection

Results are written to the phi_vault table and phi_detected is set on contracts_parsed.
"""
import logging
import re
import uuid
from datetime import datetime, timezone
from typing import Any

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")

# ---------------------------------------------------------------------------
# Layer 2: Healthcare-specific regex patterns
# ---------------------------------------------------------------------------
_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("MEDICARE_ID", re.compile(r"\b\d{11}\b")),
    ("MEDICAID_ID", re.compile(r"\b[A-Z]{2}\d{8,10}\b")),
    ("MRN", re.compile(r"\bMRN[:\s#]*\d{6,12}\b", re.IGNORECASE)),
    ("SSN", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
    ("DOB", re.compile(
        r"\b(?:DOB|date\s+of\s+birth|born)[:\s]+"
        r"(?:\d{1,2}[/-]\d{1,2}[/-]\d{2,4}|\w+ \d{1,2},? \d{4})",
        re.IGNORECASE,
    )),
    ("NPI", re.compile(r"\bNPI[:\s#]*\d{10}\b", re.IGNORECASE)),
    ("PHONE", re.compile(r"\b\(\d{3}\)\s*\d{3}-\d{4}\b")),
    ("EMAIL", re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")),
]


class PHIDetector:
    """Detect PHI in extracted contract text and store findings in phi_vault."""

    async def scan_document(
        self,
        document_version_id: str,
        text_content: str,
        created_by: str = "system",
    ) -> list[dict]:
        """Run all three detection layers and persist findings.

        Returns list of detected PHI items.
        """
        findings: list[dict] = []

        # Layer 2: Healthcare regex (fast, always runs)
        regex_hits = self._regex_scan(text_content)
        for hit in regex_hits:
            findings.append({
                "phi_id": str(uuid.uuid4()),
                "document_version_id": document_version_id,
                "phi_type": hit["phi_type"],
                "original_value": hit["value"],
                "masked_value": self._mask_value(hit["value"]),
                "detection_layer": "healthcare_regex",
                "detection_confidence": 0.85,
                "page_number": None,
                "character_offset": hit["offset"],
                "context_snippet": hit["context"],
                "created_by": created_by,
            })

        # Layer 1 & 3 are executed via SQL AI functions in the extraction
        # notebook (ai_mask, ai_extract). The notebook calls back to
        # persist those results. This service handles the regex layer
        # and the write-to-phi_vault logic.

        if findings:
            await self._persist_findings(findings)
            await self._flag_document(document_version_id)
            logger.info(
                "PHI scan: %d findings for document %s",
                len(findings),
                document_version_id,
            )

        return findings

    # ------------------------------------------------------------------
    # Layer 2: Regex scan
    # ------------------------------------------------------------------

    def _regex_scan(self, text: str) -> list[dict]:
        """Scan text with healthcare-specific regex patterns."""
        hits: list[dict] = []
        for phi_type, pattern in _PATTERNS:
            for match in pattern.finditer(text):
                start = match.start()
                # Capture surrounding context (up to 50 chars each side)
                ctx_start = max(0, start - 50)
                ctx_end = min(len(text), match.end() + 50)
                hits.append({
                    "phi_type": phi_type,
                    "value": match.group(),
                    "offset": start,
                    "context": text[ctx_start:ctx_end],
                })
        return hits

    # ------------------------------------------------------------------
    # Persistence
    # ------------------------------------------------------------------

    async def _persist_findings(self, findings: list[dict]) -> None:
        """Insert PHI findings into phi_vault using parameterized queries.

        Inserts one row at a time to use parameterized SQL safely.
        Batch sizes are small (typically < 20 findings per document).
        """
        settings = get_settings()
        for f in findings:
            await execute_sql(
                f"INSERT INTO {settings.app_catalog}.{settings.app_schema}.phi_vault "
                f"(phi_id, document_version_id, phi_type, original_value, masked_value, "
                f"detection_layer, detection_confidence, page_number, character_offset, "
                f"context_snippet, created_at, created_by) VALUES ("
                f":phi_id, :doc_version_id, :phi_type, :original_value, :masked_value, "
                f":detection_layer, :detection_confidence, :page_number, :char_offset, "
                f":context_snippet, current_timestamp(), :created_by)",
                parameters={
                    "phi_id": f["phi_id"],
                    "doc_version_id": f["document_version_id"],
                    "phi_type": f["phi_type"],
                    "original_value": f["original_value"],
                    "masked_value": f["masked_value"],
                    "detection_layer": f["detection_layer"],
                    "detection_confidence": str(f["detection_confidence"]),
                    "page_number": str(f["page_number"]) if f["page_number"] is not None else "",
                    "char_offset": str(f["character_offset"]) if f["character_offset"] is not None else "",
                    "context_snippet": f["context_snippet"] or "",
                    "created_by": f["created_by"] or "",
                },
            )

    async def _flag_document(self, document_version_id: str) -> None:
        """Set phi_detected = true on contracts_parsed for this document."""
        settings = get_settings()
        await execute_sql(
            f"UPDATE {settings.customer_catalog}.{settings.customer_schema}.contracts_parsed "
            f"SET phi_detected = true "
            f"WHERE document_version_id = :doc_id",
            parameters={"doc_id": document_version_id},
        )

    # ------------------------------------------------------------------
    # Masking
    # ------------------------------------------------------------------

    @staticmethod
    def _mask_value(value: str) -> str:
        """Mask a PHI value, preserving first and last characters."""
        if len(value) <= 4:
            return "*" * len(value)
        return value[0] + "*" * (len(value) - 2) + value[-1]


# Singleton
phi_detector = PHIDetector()
