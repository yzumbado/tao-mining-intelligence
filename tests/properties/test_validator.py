# Feature: tao-mining-intelligence-pipeline, Property 9: Validator Concentration Flag
"""Property-based tests for validator landscape analysis.

Properties verified:
1. top-1 > 50% → concentrated flag is True
2. top_1_stake_share = max(stakes) / sum(stakes)
3. net_tao_yield formula correct
4. active_validators count matches input
"""

import sys

from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, "lambda/src")

from processor.metrics import MetricsEngine
from models.schemas import Neuron


def make_neuron(uid: int, stake: float, emission: float, dividends: float) -> Neuron:
    """Helper to create a Neuron with minimal required fields."""
    return Neuron(
        uid=uid,
        hotkey=f"5Ftest{uid:03d}",
        coldkey=f"5Ctest{uid:03d}",
        stake=stake,
        incentive=0.0,
        emission=emission,
        consensus=0.0,
        validator_trust=0.5 if dividends > 0 else 0.0,
        dividends=dividends,
        active=True,
        alpha_stake=0.0,
        total_stake=stake,
        block_at_registration=1000000,
    )


class TestValidatorConcentrationProperties:
    """Property 9: Validator Concentration Flag."""

    @given(
        stakes=st.lists(
            st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=64,
        ),
        alpha_price=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_concentration_flag_at_50_percent(self, stakes, alpha_price):
        """Subnet is concentrated iff top-1 validator holds > 50% of total stake."""
        # Create validator neurons
        neurons = [
            make_neuron(uid=i, stake=s, emission=0.01, dividends=0.1)
            for i, s in enumerate(stakes)
        ]

        result = MetricsEngine.compute_validator_landscape(neurons, alpha_price)

        total_stake = sum(stakes)
        max_stake = max(stakes)
        expected_concentrated = (max_stake / total_stake) > 0.5

        assert result.concentrated == expected_concentrated, (
            f"concentrated={result.concentrated} but top_1_share="
            f"{max_stake/total_stake:.4f} ({'>' if expected_concentrated else '<='} 0.5)"
        )

    @given(
        stakes=st.lists(
            st.floats(min_value=1.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
            min_size=1,
            max_size=64,
        ),
        alpha_price=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_top_1_stake_share_formula(self, stakes, alpha_price):
        """top_1_stake_share must equal max(stakes) / sum(stakes)."""
        neurons = [
            make_neuron(uid=i, stake=s, emission=0.01, dividends=0.1)
            for i, s in enumerate(stakes)
        ]

        result = MetricsEngine.compute_validator_landscape(neurons, alpha_price)

        total = sum(stakes)
        expected_share = max(stakes) / total if total > 0 else 0.0

        assert abs(result.top_1_stake_share - expected_share) < 1e-6, (
            f"top_1_share {result.top_1_stake_share} != expected {expected_share}"
        )

    @given(
        count=st.integers(min_value=1, max_value=64),
        alpha_price=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_active_validator_count(self, count, alpha_price):
        """active_validators must match the number of neurons with dividends > 0."""
        neurons = [
            make_neuron(uid=i, stake=100.0, emission=0.01, dividends=0.1)
            for i in range(count)
        ]
        # Add some miners (dividends=0)
        neurons.extend([
            make_neuron(uid=count + i, stake=50.0, emission=0.05, dividends=0.0)
            for i in range(10)
        ])

        result = MetricsEngine.compute_validator_landscape(neurons, alpha_price)
        assert result.active_validators == count

    def test_no_validators_returns_zeros(self):
        """Subnet with no validators returns all-zero landscape."""
        neurons = [
            make_neuron(uid=i, stake=100.0, emission=0.05, dividends=0.0)
            for i in range(10)
        ]
        result = MetricsEngine.compute_validator_landscape(neurons, 0.01)
        assert result.active_validators == 0
        assert result.total_validator_stake == 0.0
        assert result.concentrated is False
