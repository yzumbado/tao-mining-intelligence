"""Unit tests for the circuit breaker module."""

import asyncio

import pytest


from src.circuit_breaker import CircuitBreaker, with_timeout, get_boto_config


class TestCircuitBreaker:
    def test_starts_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.should_attempt()
        assert not cb.is_open
        assert cb.consecutive_failures == 0

    def test_stays_closed_below_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure(TimeoutError("test"))
        cb.record_failure(TimeoutError("test"))
        assert cb.should_attempt()
        assert cb.consecutive_failures == 2

    def test_trips_at_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure(TimeoutError("1"))
        cb.record_failure(TimeoutError("2"))
        cb.record_failure(TimeoutError("3"))
        assert not cb.should_attempt()
        assert cb.is_open
        assert cb.consecutive_failures == 3

    def test_resets_on_success(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure(TimeoutError("1"))
        cb.record_failure(TimeoutError("2"))
        cb.record_success()
        assert cb.should_attempt()
        assert cb.consecutive_failures == 0

    def test_success_after_trip_resets(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure(TimeoutError("1"))
        cb.record_failure(TimeoutError("2"))
        assert cb.is_open
        cb.record_success()
        assert not cb.is_open
        assert cb.should_attempt()

    def test_manual_reset(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure(TimeoutError("1"))
        cb.record_failure(TimeoutError("2"))
        assert cb.is_open
        cb.reset()
        assert not cb.is_open
        assert cb.consecutive_failures == 0

    def test_status_string(self):
        cb = CircuitBreaker(failure_threshold=5)
        assert "CLOSED" in cb.status
        assert "0/5" in cb.status

        cb.record_failure(TimeoutError("x"))
        cb.record_failure(TimeoutError("x"))
        assert "2/5" in cb.status

        for _ in range(3):
            cb.record_failure(TimeoutError("x"))
        assert "OPEN" in cb.status

    def test_failure_threshold_of_one(self):
        cb = CircuitBreaker(failure_threshold=1)
        cb.record_failure(TimeoutError("first"))
        assert cb.is_open


class TestWithTimeout:
    @pytest.mark.asyncio
    async def test_completes_within_timeout(self):
        async def fast_op():
            return 42

        result = await with_timeout(fast_op(), timeout_seconds=5.0)
        assert result == 42

    @pytest.mark.asyncio
    async def test_raises_on_timeout(self):
        async def slow_op():
            await asyncio.sleep(10)

        with pytest.raises(TimeoutError, match="timed out after 0.1s"):
            await with_timeout(slow_op(), timeout_seconds=0.1, operation_name="slow_op")


class TestGetBotoConfig:
    def test_returns_config_with_timeouts(self):
        config = get_boto_config(connect_timeout=3, read_timeout=15, max_retries=1)
        assert config.connect_timeout == 3
        assert config.read_timeout == 15
