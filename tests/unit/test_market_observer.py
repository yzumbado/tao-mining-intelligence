"""Unit tests for the Market Observer Lambda handler.

Tests cover:
- Handler returns correct structure when no active subnets
- Chain failure handled gracefully
- Success path returns expected fields
"""

import os
from unittest.mock import patch, MagicMock

import pytest


@pytest.fixture(autouse=True)
def _reset_module_cache():
    """Reset module-level singletons between tests."""
    import src.market_observer.handler as mod
    mod._config = None
    mod._state_manager = None
    mod._cw_client = None
    yield


@pytest.fixture
def _env(monkeypatch):
    monkeypatch.setenv("PIPELINE_ENV", "local")
    monkeypatch.setenv("TABLE_NAME", "test-table")


class TestNoSubnets:
    """Test behavior when no active subnets are configured."""

    def test_returns_no_subnets_status(self, _env):
        """Handler returns early with no_subnets when list is empty."""
        from src.market_observer.handler import handle

        with patch("src.state.state_manager.StateManager.get_active_subnets", return_value=[]):
            result = handle({}, None)

        assert result["status"] == "no_subnets"


class TestChainFailure:
    """Test graceful handling when chain query fails."""

    def test_chain_timeout_returns_error(self, _env):
        """Handler logs error when chain fails (instrument catches and re-raises)."""
        from src.market_observer.handler import handle

        with patch("src.state.state_manager.StateManager.get_active_subnets", return_value=[1, 2]):
            with patch("src.market_observer.handler.asyncio.run", side_effect=Exception("timeout")):
                with pytest.raises(Exception, match="timeout"):
                    handle({}, None)


class TestSuccessfulObservation:
    """Test the happy path with mocked async result."""

    def test_returns_observed_count(self, _env):
        """Handler returns observation results on success."""
        from src.market_observer.handler import handle

        mock_result = {"status": "complete", "observed": 3, "errors": 0, "block": 8000000}
        with patch("src.state.state_manager.StateManager.get_active_subnets", return_value=[1, 2, 3]):
            with patch("src.market_observer.handler.asyncio.run", return_value=mock_result):
                with patch("src.market_observer.handler._publish_metric"):
                    result = handle({}, None)

        assert result["observed"] == 3
