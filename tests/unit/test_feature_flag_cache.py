"""Unit tests for feature flag cache — rollout_pct, user_allowlist, cache refresh."""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.feature_flag_cache import FeatureFlagCache


@pytest.fixture
def cache():
    """Fresh FeatureFlagCache with no background refresh."""
    with patch("backend.services.feature_flag_cache.get_settings") as mock_settings:
        mock_settings.return_value.app_catalog = "test"
        mock_settings.return_value.app_schema = "test_schema"
        mock_settings.return_value.feature_flag_cache_ttl_sec = 60
        return FeatureFlagCache(ttl_seconds=60)


def _populate(cache, flags: dict[str, dict]):
    """Inject flags directly into cache for testing."""
    cache._cache = flags


# ---------------------------------------------------------------------------
# Basic enable/disable
# ---------------------------------------------------------------------------
class TestBasicFlagEvaluation:
    def test_unknown_flag_returns_false(self, cache):
        assert cache.is_enabled("nonexistent_flag") is False

    def test_disabled_flag_returns_false(self, cache):
        _populate(cache, {"f": {"enabled": False, "rollout_pct": 100, "user_allowlist": []}})
        assert cache.is_enabled("f") is False

    def test_enabled_with_full_rollout(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 100, "user_allowlist": []}})
        assert cache.is_enabled("f") is True

    def test_enabled_with_zero_rollout_no_user(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 0, "user_allowlist": []}})
        assert cache.is_enabled("f") is False

    def test_enabled_zero_rollout_with_anonymous(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 0, "user_allowlist": []}})
        # No user_id → rollout_pct 0 → False
        assert cache.is_enabled("f", user_id=None) is False


# ---------------------------------------------------------------------------
# Rollout percentage (deterministic hash-based)
# ---------------------------------------------------------------------------
class TestRolloutPercentage:
    def test_50_pct_rollout_is_deterministic(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 50, "user_allowlist": []}})
        result1 = cache.is_enabled("f", user_id="user-42")
        result2 = cache.is_enabled("f", user_id="user-42")
        assert result1 == result2  # same input → same output

    def test_100_pct_rollout_always_true(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 100, "user_allowlist": []}})
        for i in range(50):
            assert cache.is_enabled("f", user_id=f"user-{i}") is True

    def test_0_pct_rollout_always_false_with_user(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 0, "user_allowlist": []}})
        for i in range(50):
            assert cache.is_enabled("f", user_id=f"user-{i}") is False

    def test_partial_rollout_splits_users(self, cache):
        """With 50% rollout, some users get True and some get False."""
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 50, "user_allowlist": []}})
        results = {cache.is_enabled("f", user_id=f"user-{i}") for i in range(200)}
        assert True in results
        assert False in results


# ---------------------------------------------------------------------------
# User allowlist
# ---------------------------------------------------------------------------
class TestUserAllowlist:
    def test_allowlisted_user_bypasses_zero_rollout(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 0, "user_allowlist": ["alice@co.com"]}})
        assert cache.is_enabled("f", user_id="alice@co.com") is True

    def test_non_allowlisted_user_obeys_rollout(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 0, "user_allowlist": ["alice@co.com"]}})
        assert cache.is_enabled("f", user_id="bob@co.com") is False

    def test_allowlist_ignored_when_flag_disabled(self, cache):
        _populate(cache, {"f": {"enabled": False, "rollout_pct": 0, "user_allowlist": ["alice@co.com"]}})
        assert cache.is_enabled("f", user_id="alice@co.com") is False

    def test_empty_allowlist_defers_to_rollout(self, cache):
        _populate(cache, {"f": {"enabled": True, "rollout_pct": 100, "user_allowlist": []}})
        assert cache.is_enabled("f", user_id="anyone") is True


# ---------------------------------------------------------------------------
# Cache refresh
# ---------------------------------------------------------------------------
class TestCacheRefresh:
    @pytest.mark.asyncio
    async def test_refresh_populates_cache(self, cache):
        with patch("backend.services.feature_flag_cache.execute_sql", new_callable=AsyncMock) as mock_sql:
            mock_sql.return_value = [
                {"flag_name": "f1", "enabled": True, "rollout_pct": 100, "user_allowlist": None, "description": "desc1"},
                {"flag_name": "f2", "enabled": "false", "rollout_pct": 50, "user_allowlist": None, "description": "desc2"},
            ]
            with patch("backend.services.feature_flag_cache.get_settings") as mock_s:
                mock_s.return_value.app_catalog = "test"
                mock_s.return_value.app_schema = "test_schema"
                await cache._refresh()

        assert cache.is_enabled("f1") is True
        assert cache.is_enabled("f2") is False  # "false" string → not enabled

    @pytest.mark.asyncio
    async def test_invalidate_forces_refresh(self, cache):
        with patch("backend.services.feature_flag_cache.execute_sql", new_callable=AsyncMock) as mock_sql:
            mock_sql.return_value = [
                {"flag_name": "f1", "enabled": True, "rollout_pct": 100, "user_allowlist": None, "description": ""},
            ]
            with patch("backend.services.feature_flag_cache.get_settings") as mock_s:
                mock_s.return_value.app_catalog = "test"
                mock_s.return_value.app_schema = "test_schema"
                await cache.invalidate()

        assert cache.is_enabled("f1") is True
        assert mock_sql.call_count == 1  # refresh was called

    def test_get_all_flags_returns_snapshot(self, cache):
        _populate(cache, {
            "a": {"enabled": True, "rollout_pct": 100, "user_allowlist": []},
            "b": {"enabled": False, "rollout_pct": 0, "user_allowlist": []},
        })
        snap = cache.get_all_flags()
        assert len(snap) == 2
        assert "a" in snap and "b" in snap

    def test_get_all_flags_is_copy(self, cache):
        _populate(cache, {"a": {"enabled": True, "rollout_pct": 100}})
        snap = cache.get_all_flags()
        snap["injected"] = {"enabled": True}
        assert "injected" not in cache._cache  # mutation doesn't leak back
