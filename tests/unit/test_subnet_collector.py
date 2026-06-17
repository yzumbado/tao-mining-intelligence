"""Unit tests for the SubnetCollector Lambda handler.

Tests cover:
- Event parsing (direct invoke and SQS formats)
- Malformed event handling
"""

import json
import os
from unittest.mock import patch, AsyncMock

import pytest


@pytest.fixture(autouse=True)
def _reset_module_cache():
    """Reset module-level singletons between tests."""
    import src.subnet_collector.handler as mod
    mod._config = None
    mod._state_manager = None
    mod._storage = None
    mod._sqs_client = None
    yield


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("PIPELINE_ENV", "local")
    monkeypatch.setenv("TABLE_NAME", "test-table")
    monkeypatch.setenv("BUCKET_NAME", "test-bucket")
    monkeypatch.setenv("PROCESS_QUEUE_URL", "http://localhost/queue")


class TestEventParsing:
    """Test that the handler correctly parses various event formats."""

    def test_direct_invoke_with_netuid(self, _env):
        """Handler parses direct invoke with netuid and calls chain."""
        from src.subnet_collector.handler import handle

        with patch("src.subnet_collector.handler._async_handle", new_callable=AsyncMock) as mock_async:
            mock_async.return_value = {"status": "complete", "netuid": 44}
            result = handle({"netuid": 44}, None)

        assert result["status"] == "complete"
        assert result["netuid"] == 44

    def test_missing_netuid_returns_error(self, _env):
        """Handler returns error for missing netuid."""
        from src.subnet_collector.handler import handle

        result = handle({}, None)
        assert result["status"] == "error"

    def test_sqs_event_format(self, _env):
        """Handler parses SQS Records format."""
        from src.subnet_collector.handler import handle

        sqs_event = {
            "Records": [{
                "body": json.dumps({"netuid": 9, "date": "2026-06-17", "cycle_id": "test"})
            }]
        }
        with patch("src.subnet_collector.handler._async_handle", new_callable=AsyncMock) as mock_async:
            mock_async.return_value = {"status": "complete", "netuid": 9}
            result = handle(sqs_event, None)

        assert result["status"] == "complete"
