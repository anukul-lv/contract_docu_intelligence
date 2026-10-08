"""Unit tests for circuit breaker state transitions."""
import time

import pytest

from backend.services.circuit_breaker import CircuitBreaker


@pytest.fixture
def breaker():
    """A circuit breaker with low thresholds for fast testing."""
    return CircuitBreaker(name="test", failure_threshold=3, recovery_timeout=1)


class TestCircuitBreaker:
    def test_starts_closed(self, breaker):
        assert breaker.state == "CLOSED"

    def test_stays_closed_under_threshold(self, breaker):
        breaker.record_failure()
        breaker.record_failure()
        assert breaker.state == "CLOSED"

    def test_opens_at_threshold(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == "OPEN"

    def test_open_rejects_calls(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        assert breaker.allow_request() is False

    def test_half_open_after_recovery(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        assert breaker.state == "OPEN"
        time.sleep(1.1)  # recovery_timeout = 1s
        assert breaker.allow_request() is True
        assert breaker.state == "HALF_OPEN"

    def test_success_closes_from_half_open(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        time.sleep(1.1)
        breaker.allow_request()  # move to HALF_OPEN
        breaker.record_success()
        assert breaker.state == "CLOSED"

    def test_failure_in_half_open_reopens(self, breaker):
        for _ in range(3):
            breaker.record_failure()
        time.sleep(1.1)
        breaker.allow_request()  # HALF_OPEN
        breaker.record_failure()
        assert breaker.state == "OPEN"

    def test_success_resets_failure_count(self, breaker):
        breaker.record_failure()
        breaker.record_failure()
        breaker.record_success()
        assert breaker._failure_count == 0
        assert breaker.state == "CLOSED"

    def test_closed_allows_requests(self, breaker):
        assert breaker.allow_request() is True
