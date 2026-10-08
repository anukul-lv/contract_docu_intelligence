"""Cache service — Semantic cache for chat responses.

Vector search against chat_cache for previously answered questions.
Cache entries are invalidated when corpus_version or trust_policy_version change.
Lookup budget: < 200ms. If exceeded, skip cache and go to live retrieval.

Target hit rate: > 30% after 1 week of usage.
"""
from __future__ import annotations

import json
import logging
import os
import time
import uuid

from databricks.sdk import WorkspaceClient

from backend.dependencies import execute_sql
from backend.config import get_settings

logger = logging.getLogger(__name__)

CACHE_LOOKUP_TIMEOUT_MS = 200


class CacheService:
    """Semantic cache for chat responses."""

    def __init__(self) -> None:
        self._client = WorkspaceClient()

    async def _get_current_versions(self) -> tuple[str, str]:
        """Get current corpus_version and trust_policy_version."""
        settings = get_settings()
        rows = await execute_sql(f"""
        SELECT
          (SELECT CAST(MAX(job_id) AS STRING) FROM {settings.app_catalog}.{settings.app_schema}.ingestion_jobs) AS corpus_version,
          (SELECT CAST(MAX(updated_at) AS STRING) FROM {settings.app_catalog}.{settings.app_schema}.confidence_thresholds) AS trust_version
        """)
        if rows:
            return (
                rows[0].get("corpus_version", "0"),
                rows[0].get("trust_version", "0"),
            )
        return ("0", "0")

    async def lookup(
        self,
        query: str,
        scope_type: str,
        scope_id: str | None,
    ) -> dict | None:
        """Vector search against chat_cache.

        Latency budget: < 200ms. If exceeded, skip cache.
        Valid only if corpus_version AND trust_policy_version match current.

        Returns:
            Cached answer payload or None.
        """
        start_ms = int(time.time() * 1000)

        try:
            corpus_ver, trust_ver = await self._get_current_versions()

            settings = get_settings()
            index_name = f"{settings.app_catalog}.{settings.app_schema}.chat_cache_index"

            # Vector search for similar questions
            result = self._client.vector_search_indexes.query_index(
                index_name=index_name,
                columns=[
                    "cache_id", "normalized_question", "answer_payload",
                    "corpus_version", "trust_policy_version",
                    "scope_type", "scope_id",
                ],
                query_text=query,
                num_results=3,
                query_type="ANN",
            )

            elapsed = int(time.time() * 1000) - start_ms
            if elapsed > CACHE_LOOKUP_TIMEOUT_MS:
                logger.info("Cache lookup exceeded %dms budget (%dms), skipping", CACHE_LOOKUP_TIMEOUT_MS, elapsed)
                return None

            if not (hasattr(result, "result") and result.result):
                return None

            cols = [c.name for c in (result.manifest.columns if result.manifest else [])]
            for row in (result.result.data_array or []):
                row_dict = dict(zip(cols, row))

                # Validate versions
                if row_dict.get("corpus_version") != corpus_ver:
                    continue
                if row_dict.get("trust_policy_version") != trust_ver:
                    continue

                # Validate scope
                if row_dict.get("scope_type") != scope_type:
                    continue
                if scope_id and row_dict.get("scope_id") != scope_id:
                    continue

                # Cache hit!
                payload = row_dict.get("answer_payload", "{}")
                if isinstance(payload, str):
                    payload = json.loads(payload)

                # Update hit count
                cache_id = row_dict.get("cache_id", "")
                await self._record_hit(cache_id)

                logger.info("Cache HIT for query (elapsed=%dms)", elapsed)
                return payload

        except Exception as e:
            logger.debug("Cache lookup failed: %s", e)

        return None

    async def _record_hit(self, cache_id: str) -> None:
        """Update hit count and last_hit_at."""
        try:
            settings = get_settings()
            await execute_sql(
                f"""
                UPDATE {settings.app_catalog}.{settings.app_schema}.chat_cache
                SET hit_count = hit_count + 1,
                    last_hit_at = current_timestamp()
                WHERE cache_id = :cache_id
                """,
                parameters={"cache_id": cache_id},
            )
        except Exception:
            pass  # Non-critical

    async def store(
        self,
        query: str,
        answer_payload: dict,
        scope_type: str,
        scope_id: str | None,
    ) -> None:
        """Store answer in cache with current versions."""
        try:
            corpus_ver, trust_ver = await self._get_current_versions()
            settings = get_settings()

            cache_id = str(uuid.uuid4())

            await execute_sql(
                f"""
                INSERT INTO {settings.app_catalog}.{settings.app_schema}.chat_cache
                (cache_id, normalized_question, scope_type, scope_id,
                 corpus_version, trust_policy_version, answer_payload)
                VALUES (
                  :cache_id, :norm_question, :scope_type, :scope_id,
                  :corpus_ver, :trust_ver, :payload
                )
                """,
                parameters={
                    "cache_id": cache_id,
                    "norm_question": query.lower().strip(),
                    "scope_type": scope_type,
                    "scope_id": scope_id or "",
                    "corpus_ver": corpus_ver,
                    "trust_ver": trust_ver,
                    "payload": json.dumps(answer_payload),
                },
            )
            logger.info("Cached answer for query")
        except Exception as e:
            logger.warning("Failed to cache answer: %s", e)
