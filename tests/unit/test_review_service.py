"""Unit tests for review service — optimistic locking, batch constraints, actions."""
import pytest
from unittest.mock import AsyncMock, patch, call

from backend.services.review_service import ReviewService, _CRITICAL_CLASSES


@pytest.fixture
def service():
    return ReviewService()


@pytest.fixture
def mock_sql():
    with patch("backend.services.review_service.execute_sql", new_callable=AsyncMock) as m:
        with patch("backend.services.review_service.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test_schema"
            mock_s.return_value.customer_catalog = "test"
            mock_s.return_value.customer_schema = "test_schema"
            yield m


# ---------------------------------------------------------------------------
# Claim (optimistic locking)
# ---------------------------------------------------------------------------
class TestClaim:
    @pytest.mark.asyncio
    async def test_claim_success_returns_true(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        result = await service.claim("rev-001", expected_version=1, assignee="reviewer@test")
        assert result is True

    @pytest.mark.asyncio
    async def test_claim_uses_merge_with_version(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        await service.claim("rev-001", expected_version=3, assignee="rev@test")
        sql = mock_sql.call_args_list[0][0][0]
        assert "MERGE INTO" in sql
        assert "version_number = src.expected_version" in sql
        assert "version_number + 1" in sql

    @pytest.mark.asyncio
    async def test_claim_conflict_returns_false(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 0}]
        result = await service.claim("rev-001", expected_version=1, assignee="reviewer@test")
        assert result is False

    @pytest.mark.asyncio
    async def test_claim_only_from_pending(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        await service.claim("rev-001", expected_version=1, assignee="rev@test")
        sql = mock_sql.call_args_list[0][0][0]
        assert "review_status = 'PENDING'" in sql

    @pytest.mark.asyncio
    async def test_claim_records_action(self, service, mock_sql):
        """Successful claim writes to review_actions."""
        mock_sql.return_value = [{"num_affected_rows": 1}]
        await service.claim("rev-001", expected_version=1, assignee="rev@test")
        # At least 2 SQL calls: MERGE + INSERT action
        assert mock_sql.call_count >= 2
        action_sql = mock_sql.call_args_list[1][0][0]
        assert "review_actions" in action_sql
        assert "CLAIM" in action_sql


# ---------------------------------------------------------------------------
# Approve
# ---------------------------------------------------------------------------
class TestApprove:
    @pytest.mark.asyncio
    async def test_approve_success(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        result = await service.approve("rev-001", expected_version=2, reviewer="rev@test")
        assert result is True

    @pytest.mark.asyncio
    async def test_approve_conflict(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 0}]
        result = await service.approve("rev-001", expected_version=2, reviewer="rev@test")
        assert result is False

    @pytest.mark.asyncio
    async def test_approve_updates_to_approved_status(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        await service.approve("rev-001", expected_version=2, reviewer="rev@test")
        sql = mock_sql.call_args_list[0][0][0]
        assert "'APPROVED'" in sql


# ---------------------------------------------------------------------------
# Correct
# ---------------------------------------------------------------------------
class TestCorrect:
    @pytest.mark.asyncio
    async def test_correct_success(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        result = await service.correct(
            "rev-001", expected_version=2, reviewer="rev@test",
            corrected_value="2024-06-01", correction_reason="Typo",
        )
        assert result is True

    @pytest.mark.asyncio
    async def test_correct_sets_human_corrected_value(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        await service.correct(
            "rev-001", expected_version=2, reviewer="rev@test",
            corrected_value="Fixed Value", correction_reason="reason",
        )
        sql = mock_sql.call_args_list[0][0][0]
        assert "human_corrected_value" in sql
        assert "Fixed Value" in sql


# ---------------------------------------------------------------------------
# Flag
# ---------------------------------------------------------------------------
class TestFlag:
    @pytest.mark.asyncio
    async def test_flag_success(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        result = await service.flag("rev-001", expected_version=2, reviewer="rev@test", reason="Suspicious")
        assert result is True

    @pytest.mark.asyncio
    async def test_flag_sets_flagged_status(self, service, mock_sql):
        mock_sql.return_value = [{"num_affected_rows": 1}]
        await service.flag("rev-001", expected_version=2, reviewer="rev@test", reason="Bad")
        sql = mock_sql.call_args_list[0][0][0]
        assert "'FLAGGED'" in sql


# ---------------------------------------------------------------------------
# Batch approve
# ---------------------------------------------------------------------------
class TestBatchApprove:
    @pytest.mark.asyncio
    async def test_batch_sql_excludes_critical_classes(self, service, mock_sql):
        mock_sql.return_value = []
        await service.batch_approve(["rev-001"], min_confidence=0.85, reviewer="admin@test")
        sql = mock_sql.call_args_list[0][0][0]
        assert "critical_financial" in sql
        assert "critical_compliance" in sql
        assert "NOT IN" in sql

    @pytest.mark.asyncio
    async def test_batch_applies_min_confidence_filter(self, service, mock_sql):
        mock_sql.return_value = []
        await service.batch_approve(["rev-001"], min_confidence=0.90, reviewer="admin@test")
        sql = mock_sql.call_args_list[0][0][0]
        assert "ai_confidence" in sql
        assert "0.9" in sql

    def test_critical_classes_constant(self):
        assert "critical_financial" in _CRITICAL_CLASSES
        assert "critical_compliance" in _CRITICAL_CLASSES


# ---------------------------------------------------------------------------
# Revert
# ---------------------------------------------------------------------------
class TestRevert:
    @pytest.mark.asyncio
    async def test_revert_not_found_returns_false(self, service, mock_sql):
        mock_sql.return_value = []
        result = await service.revert("rev-999", "admin@test", "reason")
        assert result is False


# ---------------------------------------------------------------------------
# Merge row count helper
# ---------------------------------------------------------------------------
class TestMergeRowCount:
    def test_positive_count_returns_true(self, service):
        assert service._merge_row_count([{"num_affected_rows": 3}]) is True

    def test_zero_count_returns_false(self, service):
        assert service._merge_row_count([{"num_affected_rows": 0}]) is False

    def test_missing_key_assumes_success(self, service):
        assert service._merge_row_count([{"other": 1}]) is True

    def test_empty_result_returns_true(self, service):
        assert service._merge_row_count([]) is True


# ---------------------------------------------------------------------------
# Queue listing
# ---------------------------------------------------------------------------
class TestGetQueue:
    @pytest.mark.asyncio
    async def test_returns_items_and_cursor(self, service, mock_sql):
        rows = [{"review_id": f"rev-{i}", "created_at": f"2024-01-{i+1:02d}"} for i in range(51)]
        mock_sql.side_effect = [
            rows,  # main query (returns limit+1 to detect has_more)
            [{"cnt": 100}],  # count query
        ]
        items, next_cursor, total = await service.get_queue(limit=50)
        assert len(items) == 50
        assert next_cursor is not None
        assert total == 100

    @pytest.mark.asyncio
    async def test_no_more_pages(self, service, mock_sql):
        rows = [{"review_id": "rev-1", "created_at": "2024-01-01"}]
        mock_sql.side_effect = [rows, [{"cnt": 1}]]
        items, next_cursor, total = await service.get_queue(limit=50)
        assert len(items) == 1
        assert next_cursor is None
