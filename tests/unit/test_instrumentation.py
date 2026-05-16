"""Unit tests for the instrumentation module."""

import json
import logging
import sys

import pytest

sys.path.insert(0, "lambda/src")

from instrumentation import (
    init_tracing,
    set_trace_id,
    get_trace_id,
    get_cycle_id,
    instrument,
    is_retryable,
    truncate_coldkey,
)


class TestInitTracing:
    def test_generates_trace_id_with_cycle_prefix(self):
        trace_id = init_tracing("2026-05-15")
        assert trace_id.startswith("cycle-2026-05-15-")
        assert len(trace_id) == len("cycle-2026-05-15-") + 8  # 8 hex chars

    def test_sets_global_state(self):
        init_tracing("2026-05-15")
        assert get_trace_id() is not None
        assert get_cycle_id() == "2026-05-15"

    def test_different_calls_produce_different_ids(self):
        id1 = init_tracing("2026-05-15")
        id2 = init_tracing("2026-05-15")
        assert id1 != id2


class TestSetTraceId:
    def test_sets_trace_and_cycle(self):
        set_trace_id("custom-trace-123", "2026-05-16")
        assert get_trace_id() == "custom-trace-123"
        assert get_cycle_id() == "2026-05-16"


class TestInstrument:
    def test_success_logs_duration(self, caplog):
        init_tracing("2026-05-15")
        with caplog.at_level(logging.INFO, logger="tao-pipeline"):
            with instrument("test", "test_op", netuid=1) as ctx:
                ctx["extra_field"] = "hello"

        # Find the success log entry
        success_logs = [r for r in caplog.records if "success" in r.getMessage()]
        assert len(success_logs) >= 1
        log_data = json.loads(success_logs[-1].getMessage())
        assert log_data["status"] == "success"
        assert log_data["component"] == "test"
        assert log_data["operation"] == "test_op"
        assert log_data["netuid"] == 1
        assert "duration_ms" in log_data
        assert log_data["duration_ms"] >= 0

    def test_error_logs_exception(self, caplog):
        init_tracing("2026-05-15")
        with caplog.at_level(logging.INFO, logger="tao-pipeline"):
            with pytest.raises(ValueError):
                with instrument("test", "failing_op") as ctx:
                    raise ValueError("test error")

        error_logs = [r for r in caplog.records if "error" in r.getMessage()]
        assert len(error_logs) >= 1
        log_data = json.loads(error_logs[-1].getMessage())
        assert log_data["status"] == "error"
        assert "ValueError: test error" in log_data["error"]
        assert "retryable" in log_data

    def test_none_netuid_excluded_from_log(self, caplog):
        init_tracing("2026-05-15")
        with caplog.at_level(logging.INFO, logger="tao-pipeline"):
            with instrument("test", "no_netuid"):
                pass

        success_logs = [r for r in caplog.records if "success" in r.getMessage()]
        log_data = json.loads(success_logs[-1].getMessage())
        assert "netuid" not in log_data  # None values excluded


class TestIsRetryable:
    def test_timeout_is_retryable(self):
        assert is_retryable(TimeoutError("timed out"))

    def test_connection_error_is_retryable(self):
        assert is_retryable(ConnectionError("connection reset"))

    def test_os_error_is_retryable(self):
        assert is_retryable(OSError("network unreachable"))

    def test_value_error_not_retryable(self):
        assert not is_retryable(ValueError("bad data"))

    def test_key_error_not_retryable(self):
        assert not is_retryable(KeyError("missing field"))

    def test_throttling_message_is_retryable(self):
        assert is_retryable(Exception("Request throttled by server"))

    def test_rate_limit_message_is_retryable(self):
        assert is_retryable(Exception("rate limit exceeded"))


class TestTruncateColdkey:
    def test_long_key_truncated(self):
        key = "5FHneW46xGXgs5mUiveU4sbTyGBzmstUPZtBqBJELhiLg5dc"
        assert truncate_coldkey(key) == "5FHneW46xGXg..."

    def test_short_key_unchanged(self):
        assert truncate_coldkey("5FHneW") == "5FHneW"

    def test_exactly_12_chars_unchanged(self):
        assert truncate_coldkey("123456789012") == "123456789012"
