"""Unit tests for HIPAA audit service — event logging, PHI access flagging."""
import pytest
from unittest.mock import AsyncMock, patch

from backend.services.hipaa_audit import HIPAAAuditService


@pytest.fixture
def audit_svc():
    return HIPAAAuditService()


@pytest.fixture
def mock_sql():
    with patch("backend.services.hipaa_audit.execute_sql", new_callable=AsyncMock) as m:
        with patch("backend.services.hipaa_audit.get_settings") as mock_s:
            mock_s.return_value.app_catalog = "test"
            mock_s.return_value.app_schema = "test_schema"
            yield m


# ---------------------------------------------------------------------------
# Basic event logging
# ---------------------------------------------------------------------------
class TestLogEvent:
    @pytest.mark.asyncio
    async def test_inserts_into_hipaa_audit_log(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="DOCUMENT_ACCESSED",
            user_identity="user@test.com",
            user_role="REVIEWER",
            resource_type="document",
            resource_id="doc-001",
            action="view",
        )
        assert mock_sql.called
        sql = mock_sql.call_args[0][0]
        assert "INSERT INTO" in sql
        assert "hipaa_audit_log" in sql

    @pytest.mark.asyncio
    async def test_contains_all_required_fields(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="REVIEW_ACTION",
            user_identity="rev@test.com",
            user_role="REVIEWER",
            resource_type="review_item",
            resource_id="rev-001",
            action="approve",
        )
        sql = mock_sql.call_args[0][0]
        for field in ["event_id", "event_timestamp", "event_type", "user_identity",
                      "user_role", "resource_type", "resource_id", "action", "outcome"]:
            assert field in sql

    @pytest.mark.asyncio
    async def test_default_outcome_is_success(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="TEST",
            user_identity="u@t.com",
            user_role="ADMIN",
            resource_type="test",
            resource_id="t-1",
            action="test",
        )
        sql = mock_sql.call_args[0][0]
        assert "SUCCESS" in sql

    @pytest.mark.asyncio
    async def test_custom_outcome(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="LOGIN_FAILED",
            user_identity="u@t.com",
            user_role="VIEWER",
            resource_type="session",
            resource_id="sess-1",
            action="login",
            outcome="FAILURE",
        )
        sql = mock_sql.call_args[0][0]
        assert "FAILURE" in sql


# ---------------------------------------------------------------------------
# PHI access flagging
# ---------------------------------------------------------------------------
class TestPHIAccessFlagging:
    @pytest.mark.asyncio
    async def test_phi_accessed_true_in_sql(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="PHI_ACCESSED",
            user_identity="user@test.com",
            user_role="ADMIN",
            resource_type="phi_vault",
            resource_id="phi-001",
            action="view_phi",
            phi_accessed=True,
        )
        sql = mock_sql.call_args[0][0]
        assert "true" in sql.lower()

    @pytest.mark.asyncio
    async def test_phi_fields_accessed_as_array(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="PHI_ACCESSED",
            user_identity="user@test.com",
            user_role="ADMIN",
            resource_type="phi_vault",
            resource_id="phi-001",
            action="view_phi",
            phi_accessed=True,
            phi_fields_accessed=["SSN", "DOB", "MRN"],
        )
        sql = mock_sql.call_args[0][0]
        assert "ARRAY" in sql
        assert "SSN" in sql
        assert "DOB" in sql
        assert "MRN" in sql

    @pytest.mark.asyncio
    async def test_phi_not_accessed_is_false(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="DOCUMENT_ACCESSED",
            user_identity="user@test.com",
            user_role="VIEWER",
            resource_type="document",
            resource_id="doc-001",
            action="view",
            phi_accessed=False,
        )
        sql = mock_sql.call_args[0][0]
        assert "false" in sql.lower()

    @pytest.mark.asyncio
    async def test_no_phi_fields_uses_null(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="TEST",
            user_identity="u@t.com",
            user_role="ADMIN",
            resource_type="test",
            resource_id="t-1",
            action="test",
        )
        sql = mock_sql.call_args[0][0]
        assert "NULL" in sql  # phi_fields_accessed defaults to NULL


# ---------------------------------------------------------------------------
# SQL injection safety
# ---------------------------------------------------------------------------
class TestSQLSafety:
    @pytest.mark.asyncio
    async def test_escapes_single_quotes(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="TEST",
            user_identity="user's@test.com",
            user_role="VIEWER",
            resource_type="test's",
            resource_id="test-001",
            action="test",
        )
        assert mock_sql.called
        sql = mock_sql.call_args[0][0]
        assert "user''s@test.com" in sql  # doubled single quote

    @pytest.mark.asyncio
    async def test_null_optional_fields(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="TEST",
            user_identity="u@t.com",
            user_role="VIEWER",
            resource_type="test",
            resource_id="t-1",
            action="test",
            source_ip=None,
            session_id=None,
            request_id=None,
        )
        sql = mock_sql.call_args[0][0]
        assert sql.count("NULL") >= 3  # source_ip, session_id, request_id

    @pytest.mark.asyncio
    async def test_details_serialized_as_json(self, audit_svc, mock_sql):
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="TEST",
            user_identity="u@t.com",
            user_role="ADMIN",
            resource_type="test",
            resource_id="t-1",
            action="test",
            details={"key": "value", "count": 42},
        )
        sql = mock_sql.call_args[0][0]
        assert '"key"' in sql
        assert '"value"' in sql


# ---------------------------------------------------------------------------
# Failure resilience
# ---------------------------------------------------------------------------
class TestFailureResilience:
    @pytest.mark.asyncio
    async def test_sql_error_does_not_raise(self, audit_svc, mock_sql):
        """Audit failures must NEVER crash the request."""
        mock_sql.side_effect = Exception("SQL warehouse unavailable")
        # Should not raise
        await audit_svc.log_event(
            event_type="TEST",
            user_identity="u@t.com",
            user_role="VIEWER",
            resource_type="test",
            resource_id="t-1",
            action="test",
        )

    @pytest.mark.asyncio
    async def test_append_only_no_update_or_delete(self, audit_svc, mock_sql):
        """Audit table is append-only: no UPDATE or DELETE in SQL."""
        mock_sql.return_value = []
        await audit_svc.log_event(
            event_type="TEST",
            user_identity="u@t.com",
            user_role="ADMIN",
            resource_type="test",
            resource_id="t-1",
            action="test",
        )
        sql = mock_sql.call_args[0][0]
        assert "INSERT" in sql
        assert "UPDATE" not in sql.split("VALUES")[0]  # no UPDATE in the statement
        assert "DELETE" not in sql
