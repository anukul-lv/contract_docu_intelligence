"""Checksum and near-duplicate detection service."""
import logging

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")


class DedupService:
    """Checksum and near-duplicate detection against contracts_parsed."""

    async def check_checksums(self, checksums: list[str]) -> list[dict]:
        """Match checksums against contracts_parsed.file_checksum.

        Returns a list of dicts for each checksum that already exists:
          [{"checksum": "abc123", "existing_document_version_id": "...", "file_name": "..."}]
        """
        if not checksums:
            return []

        settings = get_settings()
        # Build parameterized IN clause
        placeholders = ", ".join(f":cs_{i}" for i in range(len(checksums)))
        params = {f"cs_{i}": cs for i, cs in enumerate(checksums)}

        rows = await execute_sql(
            f"""
            SELECT file_checksum, document_version_id, file_name
            FROM {settings.customer_catalog}.{settings.customer_schema}.contracts_parsed
            WHERE file_checksum IN ({placeholders})
            """,
            parameters=params,
        )

        return [
            {
                "checksum": row["file_checksum"],
                "existing_document_version_id": row["document_version_id"],
                "file_name": row.get("file_name", ""),
            }
            for row in rows
        ]

    async def check_near_duplicates(self, file_path: str) -> list[dict]:
        """Near-duplicate detection using content similarity.

        Placeholder for future ai_similarity integration (R2+).
        Currently returns an empty list.
        """
        # TODO(R2): Integrate ai_similarity for near-duplicate detection
        # once vector search indexes are built in R2_01.
        logger.debug("Near-duplicate check for %s (stub — returning empty)", file_path)
        return []


# Singleton
dedup_service = DedupService()
