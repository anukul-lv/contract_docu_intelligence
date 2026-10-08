"""In-memory feature flag cache with background refresh."""
import asyncio
import hashlib
import logging
from threading import Lock

from backend.config import get_settings
from backend.dependencies import execute_sql

logger = logging.getLogger("healthcontracts")


class FeatureFlagCache:
    """In-memory cache of feature flags with background refresh.

    Flag reads never hit Delta on the hot path. The cache is refreshed
    every ``ttl_seconds`` via a background asyncio task.
    """

    def __init__(self, ttl_seconds: int = 60):
        self._cache: dict[str, dict] = {}
        self._lock = Lock()
        self._ttl = ttl_seconds

    async def start(self) -> None:
        """Load initial flags and start background refresh task."""
        await self._refresh()
        asyncio.create_task(self._background_refresh())
        logger.info("Feature flag cache started (TTL=%ds)", self._ttl)

    async def _background_refresh(self) -> None:
        """Continuously refresh flags on the configured interval."""
        while True:
            await asyncio.sleep(self._ttl)
            try:
                await self._refresh()
            except Exception as exc:
                logger.warning("Feature flag refresh failed: %s", exc)

    async def _refresh(self) -> None:
        """SELECT * FROM feature_flags and update in-memory cache."""
        settings = get_settings()
        rows = await execute_sql(
            f"SELECT flag_name, enabled, rollout_pct, user_allowlist, description "
            f"FROM {settings.app_catalog}.{settings.app_schema}.feature_flags"
        )
        new_cache: dict[str, dict] = {}
        for row in rows:
            new_cache[row["flag_name"]] = {
                "enabled": row["enabled"] in (True, "true", "1"),
                "rollout_pct": int(row.get("rollout_pct") or 0),
                "user_allowlist": row.get("user_allowlist") or [],
                "description": row.get("description", ""),
            }
        with self._lock:
            self._cache = new_cache
        logger.debug("Feature flag cache refreshed: %d flags loaded", len(new_cache))

    def is_enabled(self, flag_name: str, user_id: str | None = None) -> bool:
        """Check if a flag is enabled, considering rollout_pct and user_allowlist."""
        with self._lock:
            flag = self._cache.get(flag_name)
        if not flag:
            return False
        if not flag["enabled"]:
            return False
        # User allowlist override
        if user_id and flag.get("user_allowlist") and user_id in flag["user_allowlist"]:
            return True
        # Rollout percentage (100 = fully rolled out, 0 = disabled)
        if flag.get("rollout_pct", 0) >= 100:
            return True
        if flag.get("rollout_pct", 0) <= 0:
            return False
        # Deterministic hash-based rollout for partial percentages
        if user_id:
            hash_val = int(hashlib.md5(f"{flag_name}:{user_id}".encode()).hexdigest(), 16)
            return (hash_val % 100) < flag["rollout_pct"]
        return False

    def get_all_flags(self) -> dict[str, dict]:
        """Return a snapshot of all flags (for admin API)."""
        with self._lock:
            return dict(self._cache)

    async def invalidate(self) -> None:
        """Force immediate refresh (called on PUT /settings/flags)."""
        await self._refresh()
        logger.info("Feature flag cache force-refreshed")


# Singleton instance — initialized at app startup
flag_cache = FeatureFlagCache(ttl_seconds=get_settings().feature_flag_cache_ttl_sec)
