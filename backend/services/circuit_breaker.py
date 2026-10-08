"""Circuit breaker for external service calls (AI Gateway, SQL Warehouse, AI Search)."""
import logging
import time

logger = logging.getLogger("healthcontracts")


class CircuitBreaker:
    """Simple circuit breaker with three states: CLOSED, OPEN, HALF_OPEN."""

    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"

    def __init__(
        self,
        name: str,
        failure_threshold: int = 5,
        recovery_timeout_sec: int = 60,
    ):
        self.name = name
        self.state = self.CLOSED
        self.failure_count = 0
        self.failure_threshold = failure_threshold
        self.recovery_timeout_sec = recovery_timeout_sec
        self.last_failure_time: float | None = None

    def record_failure(self) -> None:
        """Record a failure. Trips the breaker when threshold is reached."""
        self.failure_count += 1
        self.last_failure_time = time.time()
        if self.failure_count >= self.failure_threshold:
            previous = self.state
            self.state = self.OPEN
            if previous != self.OPEN:
                logger.error(
                    "Circuit breaker '%s' OPENED after %d failures",
                    self.name,
                    self.failure_count,
                )

    def record_success(self) -> None:
        """Record a success. Resets the breaker to CLOSED."""
        if self.state != self.CLOSED:
            logger.info("Circuit breaker '%s' recovered -> CLOSED", self.name)
        self.failure_count = 0
        self.state = self.CLOSED

    def can_execute(self) -> bool:
        """Check whether a request should be allowed through."""
        if self.state == self.CLOSED:
            return True
        if self.state == self.OPEN:
            if (
                self.last_failure_time
                and time.time() - self.last_failure_time > self.recovery_timeout_sec
            ):
                self.state = self.HALF_OPEN
                logger.info("Circuit breaker '%s' -> HALF_OPEN (probing)", self.name)
                return True
            return False
        # HALF_OPEN: allow one probe request
        return True

    async def call(self, func):
        """Execute an async callable with circuit breaker protection.

        Checks if the breaker allows execution, calls the function,
        and records success or failure accordingly.

        Args:
            func: An async callable (no arguments) to execute.

        Returns:
            The result of the callable.

        Raises:
            RuntimeError: If the circuit breaker is OPEN.
            Exception: Any exception from the callable (after recording failure).
        """
        if not self.can_execute():
            raise RuntimeError(
                f"Circuit breaker '{self.name}' is OPEN — request rejected"
            )
        try:
            result = await func()
            self.record_success()
            return result
        except Exception:
            self.record_failure()
            raise


# Pre-configured breaker instances for each external dependency
ai_gateway_breaker = CircuitBreaker("ai_gateway", failure_threshold=5, recovery_timeout_sec=60)
sql_warehouse_breaker = CircuitBreaker("sql_warehouse", failure_threshold=10, recovery_timeout_sec=30)
ai_search_breaker = CircuitBreaker("ai_search", failure_threshold=5, recovery_timeout_sec=60)
