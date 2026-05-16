# Feature: tao-mining-intelligence-pipeline, Property 8: Miner Churn Computation
"""Property-based tests for miner churn computation.

Properties verified:
1. churn_rate = (|new| + |departed|) / |current|
2. new_miners = current - previous (set difference)
3. departed_miners = previous - current (set difference)
4. trend: INCREASING when net > +5%, DECREASING when < -5%, STABLE otherwise
"""

import sys

from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, "lambda/src")

from processor.metrics import MetricsEngine
from models.enums import CompetitionTrend


# Strategy for generating hotkey-like strings
hotkey_strategy = st.text(
    alphabet="abcdefghijklmnopqrstuvwxyz0123456789",
    min_size=10,
    max_size=10,
)

hotkey_set_strategy = st.frozensets(hotkey_strategy, min_size=1, max_size=100)


class TestMinerChurnProperties:
    """Property 8: Miner Churn Computation."""

    @given(
        current=hotkey_set_strategy,
        previous=hotkey_set_strategy,
    )
    @settings(max_examples=200)
    def test_churn_rate_formula(self, current, previous):
        """churn_rate must equal (|new| + |departed|) / |current|."""
        current_set = set(current)
        previous_set = set(previous)
        assume(len(current_set) > 0)

        # Simple registrations list (all active, same block)
        registrations = [
            {"block_at_registration": 1000, "active": True}
            for _ in current_set
        ]

        result = MetricsEngine.compute_miner_churn(
            current_hotkeys=current_set,
            previous_hotkeys=previous_set,
            current_registrations=registrations,
            current_block=5000,
        )

        expected_new = len(current_set - previous_set)
        expected_departed = len(previous_set - current_set)
        expected_churn = (expected_new + expected_departed) / len(current_set)
        expected_churn = min(1.0, expected_churn)  # Clamped

        assert abs(result.daily_churn_rate - expected_churn) < 1e-10, (
            f"Churn rate {result.daily_churn_rate} != expected {expected_churn}"
        )

    @given(
        current=hotkey_set_strategy,
        previous=hotkey_set_strategy,
    )
    @settings(max_examples=200)
    def test_new_miners_is_set_difference(self, current, previous):
        """new_registrations must equal |current - previous|."""
        current_set = set(current)
        previous_set = set(previous)
        assume(len(current_set) > 0)

        registrations = [{"block_at_registration": 1000, "active": True} for _ in current_set]

        result = MetricsEngine.compute_miner_churn(
            current_hotkeys=current_set,
            previous_hotkeys=previous_set,
            current_registrations=registrations,
            current_block=5000,
        )

        expected_new = len(current_set - previous_set)
        assert result.new_registrations == expected_new

    @given(
        current=hotkey_set_strategy,
        previous=hotkey_set_strategy,
    )
    @settings(max_examples=200)
    def test_departed_miners_is_set_difference(self, current, previous):
        """deregistrations must equal |previous - current|."""
        current_set = set(current)
        previous_set = set(previous)
        assume(len(current_set) > 0)

        registrations = [{"block_at_registration": 1000, "active": True} for _ in current_set]

        result = MetricsEngine.compute_miner_churn(
            current_hotkeys=current_set,
            previous_hotkeys=previous_set,
            current_registrations=registrations,
            current_block=5000,
        )

        expected_departed = len(previous_set - current_set)
        assert result.deregistrations == expected_departed

    @given(
        base_size=st.integers(min_value=20, max_value=100),
        new_count=st.integers(min_value=0, max_value=50),
        departed_count=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_trend_classification(self, base_size, new_count, departed_count):
        """Trend must be INCREASING/DECREASING/STABLE based on net change %."""
        # Build sets with known overlap
        base_keys = {f"key_{i}" for i in range(base_size)}
        new_keys = {f"new_{i}" for i in range(new_count)}
        departed_keys = {f"dep_{i}" for i in range(departed_count)}

        previous_set = base_keys | departed_keys
        current_set = base_keys | new_keys
        assume(len(current_set) > 0)

        registrations = [{"block_at_registration": 1000, "active": True} for _ in current_set]

        result = MetricsEngine.compute_miner_churn(
            current_hotkeys=current_set,
            previous_hotkeys=previous_set,
            current_registrations=registrations,
            current_block=5000,
        )

        net_change = new_count - departed_count
        net_pct = net_change / len(current_set)

        if net_pct > 0.05:
            assert result.competition_trend == CompetitionTrend.INCREASING
        elif net_pct < -0.05:
            assert result.competition_trend == CompetitionTrend.DECREASING
        else:
            assert result.competition_trend == CompetitionTrend.STABLE

    @given(
        current=hotkey_set_strategy,
        previous=hotkey_set_strategy,
    )
    @settings(max_examples=100)
    def test_churn_rate_in_valid_range(self, current, previous):
        """Churn rate must be in [0.0, 1.0]."""
        current_set = set(current)
        previous_set = set(previous)
        assume(len(current_set) > 0)

        registrations = [{"block_at_registration": 1000, "active": True} for _ in current_set]

        result = MetricsEngine.compute_miner_churn(
            current_hotkeys=current_set,
            previous_hotkeys=previous_set,
            current_registrations=registrations,
            current_block=5000,
        )

        assert 0.0 <= result.daily_churn_rate <= 1.0
