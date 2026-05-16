"""Circuit breaker and timeout utilities.

Provides:
- CircuitBreaker: Trips after N consecutive failures, preventing further attempts
- Per-operation timeout wrapper using asyncio.timeout()
- boto3 client configuration with explicit timeouts

The circuit breaker prevents the Collector from wasting the entire Lambda
execution time when the Finney endpoint is completely down.
"""

import asyncio
import logging
from dataclasses import dataclass, field
from typing import Any, Callable, TypeVar

from botocore.config import Config as BotoConfig

logger = logging.getLogger("tao-pipeline")

T = TypeVar("T")


@dataclass
class CircuitBreaker:
    """Circuit breaker that trips after N consecutive failures.

    When open (tripped), should_attempt() returns False, signaling the caller
    to skip the operation. Resets on any successful operation.

    Attributes:
        failure_threshold: Number of consecutive failures before tripping.
        consecutive_failures: Current count of consecutive failures.
        is_open: Whether the circuit breaker is currently tripped.
    """

    failure_threshold: int = 5
    consecutive_failures: int = field(default=0, init=False)
    is_open: bool = field(default=False, init=False)
    _failure_details: list[str] = field(default_factory=list, init=False)

    def record_success(self) -> None:
        """Record a successful operation. Resets the failure counter."""
        self.consecutive_failures = 0
        self.is_open = False
        self._failure_details.clear()

    def record_failure(self, error: Exception | None = None) -> None:
        """Record a failed operation. May trip the breaker.

        Args:
            error: Optional exception for logging context.
        """
        self.consecutive_failures += 1
        if error:
            self._failure_details.append(
                f"{type(error).__name__}: {str(error)[:100]}"
            )

        if self.consecutive_failures >= self.failure_threshold:
            self.is_open = True
            logger.error(
                f"Circuit breaker TRIPPED after {self.consecutive_failures} "
                f"consecutive failures. Recent errors: {self._failure_details[-3:]}"
            )

    def should_attempt(self) -> bool:
        """Check if an operation should be attempted.

        Returns:
            True if the circuit is closed (safe to attempt).
            False if the circuit is open (skip the operation).
        """
        return not self.is_open

    def reset(self) -> None:
        """Manually reset the circuit breaker."""
        self.consecutive_failures = 0
        self.is_open = False
        self._failure_details.clear()

    @property
    def status(self) -> str:
        """Human-readable status string."""
        if self.is_open:
            return f"OPEN (tripped after {self.consecutive_failures} failures)"
        return f"CLOSED ({self.consecutive_failures}/{self.failure_threshold} failures)"


async def with_timeout(
    coro: Any,
    timeout_seconds: float,
    operation_name: str = "operation",
) -> Any:
    """Execute an async coroutine with a timeout.

    Args:
        coro: The coroutine to execute.
        timeout_seconds: Maximum seconds to wait.
        operation_name: Name for error messages.

    Returns:
        The coroutine's result.

    Raises:
        TimeoutError: If the operation exceeds the timeout.
    """
    try:
        async with asyncio.timeout(timeout_seconds):
            return await coro
    except asyncio.TimeoutError:
        raise TimeoutError(
            f"{operation_name} timed out after {timeout_seconds}s"
        )


def get_boto_config(
    connect_timeout: int = 5,
    read_timeout: int = 30,
    max_retries: int = 2,
) -> BotoConfig:
    """Create a boto3 Config with explicit timeouts.

    Prevents hanging on AWS service issues by enforcing connection
    and read timeouts at the client level.

    Args:
        connect_timeout: Seconds to wait for connection establishment.
        read_timeout: Seconds to wait for response data.
        max_retries: Maximum retry attempts for transient errors.

    Returns:
        A botocore Config object for use with boto3 clients.
    """
    return BotoConfig(
        connect_timeout=connect_timeout,
        read_timeout=read_timeout,
        retries={"max_attempts": max_retries, "mode": "adaptive"},
    )


# Default boto3 config for all AWS operations
DEFAULT_BOTO_CONFIG = get_boto_config(
    connect_timeout=5,
    read_timeout=30,
    max_retries=2,
)

# Timeout constants (configurable via thresholds in production)
DEFAULT_METAGRAPH_TIMEOUT_SECONDS = 30.0
DEFAULT_QUERY_TIMEOUT_SECONDS = 10.0
DEFAULT_PRICE_API_TIMEOUT_SECONDS = 10.0
