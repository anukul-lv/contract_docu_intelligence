"""Unit tests for extraction engine — idempotency dedup, batch sizing, state machine."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from backend.services.extraction_engine import ExtractionEngine, _DEDUP_WINDOW_HOURS


@pytest.fixture
def engine():
    return ExtractionEngine()


# ---------------------------------------------------------------------------
# Adaptive batch sizing: ≤10→all, >200→50, default 25
# ---------------------------------------------------------------------------
class TestBatchSizing:
    def test_tiny_batch_all(self, engine):
        assert engine._compute_batch_size(3) == 3

    def test_small_batch_all(self, engine):
        assert engine._compute_batch_size(5) == 5

    def test_boundary_10_all(self, engine):
        assert engine._compute_batch_size(10) == 10

    def test_medium_uses_default_25(self, engine):
        assert engine._compute_batch_size(50) == 25

    def test_boundary_200_still_default(self, engine):
        assert engine._compute_batch_size(200) == 25

    def test_large_201_uses_50(self, engine):
        assert engine._compute_batch_size(201) == 50

    def test_very_large(self, engine):
        assert engine._compute_batch_size(5000) == 50

    def test_single_document(self, engine):
        assert engine._compute_batch_size(1) == 1


# ---------------------------------------------------------------------------
# Idempotency key dedup (24-hour window)
# ---------------------------------------------------------------------------
class TestIdempotency:
    @pytest.mark.asyncio
    async def test_returns_existing_run_when_dedup_hit(self, engine):
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test"
            mock_sql.return_value = [{"run_id": "existing-run", "state": "COMPLETED"}]
            result = await engine._check_idempotency("key-123")
            assert result is not None
            assert result["run_id"] == "existing-run"
            assert result["deduplicated"] is True

    @pytest.mark.asyncio
    async def test_returns_none_when_no_match(self, engine):
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test"
            mock_sql.return_value = []
            result = await engine._check_idempotency("new-key")
            assert result is None

    @pytest.mark.asyncio
    async def test_dedup_query_uses_24h_window(self, engine):
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test"
            mock_sql.return_value = []
            await engine._check_idempotency("test-key")
            sql = mock_sql.call_args[0][0]
            assert "INTERVAL" in sql or "24" in sql or str(_DEDUP_WINDOW_HOURS) in sql

    def test_dedup_window_is_24h(self):
        assert _DEDUP_WINDOW_HOURS == 24


# ---------------------------------------------------------------------------
# State machine transitions
# ---------------------------------------------------------------------------
class TestStateMachine:
    """Verify the docstring-defined state machine via start_extraction."""

    @pytest.mark.asyncio
    async def test_idempotent_return_skips_job_creation(self, engine):
        """When idempotency key hits, no new job is created."""
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_settings") as mock_settings, \
             patch("backend.services.extraction_engine.get_workspace_client") as mock_wc:

            mock_settings.return_value.app_catalog = "test"
            mock_settings.return_value.app_schema = "test"
            mock_sql.return_value = [{"run_id": "dup-run", "state": "RUNNING"}]

            result = await engine.start_extraction(
                volume_path="/Volumes/test",
                file_list=["a.pdf"],
                output_catalog="test",
                output_schema="test",
                profile="general_healthcare",
                auto_enrich=False,
                healthcare_mode=True,
                idempotency_key="dup-key",
                created_by="test@user",
            )
            assert result["deduplicated"] is True
            assert result["run_id"] == "dup-run"
            mock_wc.return_value.jobs.run_now.assert_not_called()

    @pytest.mark.asyncio
    async def test_submit_failure_transitions_to_submit_failed(self, engine):
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_workspace_client") as mock_wc, \
             patch("backend.services.extraction_engine.job_tracker") as mock_tracker, \
             patch("backend.services.extraction_engine.cost_tracker") as mock_cost, \
             patch("backend.services.extraction_engine.get_profile_snapshot") as mock_profile, \
             patch("backend.services.extraction_engine.get_settings") as mock_settings:

            settings = MagicMock()
            settings.app_catalog = "test"
            settings.app_schema = "test"
            settings.extraction_job_template_id = "123"
            mock_settings.return_value = settings
            mock_profile.return_value = {"profile": "general_healthcare"}
            mock_cost.estimate_run_cost.return_value = 1.5

            mock_sql.return_value = []  # no idempotency hit
            mock_tracker.write_event = AsyncMock()
            mock_tracker.update_job_state = AsyncMock()

            client = MagicMock()
            client.jobs.run_now.side_effect = Exception("Connection refused")
            mock_wc.return_value = client

            with pytest.raises(RuntimeError, match="Job submission failed"):
                await engine.start_extraction(
                    volume_path="/Volumes/test",
                    file_list=["a.pdf"],
                    output_catalog="test",
                    output_schema="test",
                    profile="general_healthcare",
                    auto_enrich=False,
                    healthcare_mode=True,
                    idempotency_key="test-key",
                    created_by="test@user",
                )


# ---------------------------------------------------------------------------
# Get status and cancel
# ---------------------------------------------------------------------------
class TestGetStatus:
    @pytest.mark.asyncio
    async def test_returns_job_state(self, engine):
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test"
            mock_sql.return_value = [
                {"run_id": "r-1", "state": "RUNNING", "total_documents": 50,
                 "completed_documents": 25, "failed_documents": 0}
            ]
            result = await engine.get_status("r-1")
            assert result is not None
            assert result["state"] == "RUNNING"

    @pytest.mark.asyncio
    async def test_returns_none_for_unknown_run(self, engine):
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test"
            mock_sql.return_value = []
            result = await engine.get_status("nonexistent")
            assert result is None


class TestCancel:
    @pytest.mark.asyncio
    async def test_cancel_calls_workspace_client(self, engine):
        with patch("backend.services.extraction_engine.execute_sql", new_callable=AsyncMock) as mock_sql, \
             patch("backend.services.extraction_engine.get_workspace_client") as mock_wc, \
             patch("backend.services.extraction_engine.job_tracker") as mock_tracker, \
             patch("backend.services.extraction_engine.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test"
            mock_sql.return_value = [{"run_id": "r-1", "state": "RUNNING", "databricks_run_id": 12345}]
            mock_tracker.write_event = AsyncMock()
            mock_tracker.update_job_state = AsyncMock()

            client = MagicMock()
            mock_wc.return_value = client

            await engine.cancel("r-1", cancelled_by="admin@test")
            client.jobs.cancel_run.assert_called_once()
