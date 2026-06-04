# Feature: tao-mining-intelligence-pipeline, Property 1: Deregistration Risk Score Invariants
"""Property-based tests for deregistration risk scoring.

Properties verified:
1. All risk scores are in [0.0, 1.0]
2. Immune miners always get risk score 0.0
3. Non-full subnets: all miners get risk score 0.0
4. On full subnets, risk scores are monotonically non-increasing as emission rank improves

Uses the SAME MetricsEngine.compute_deregistration_risk method that production uses,
with real Neuron objects — no standalone test-only functions.
"""

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.processor.metrics import MetricsEngine
from src.models.schemas import Neuron


# =============================================================================
# Hypothesis Strategies
# =============================================================================

CURRENT_BLOCK = 5_000_000
IMMUNITY_PERIOD = 7200


def _make_neuron(uid: int, emission: float, block_at_registration: int) -> Neuron:
    """Create a minimal Neuron for deregistration risk testing."""
    return Neuron(
        uid=uid,
        hotkey=f"5{'H' * 47}{uid:03d}",
        coldkey=f"5{'C' * 47}{uid:03d}",
        stake=0.0,
        incentive=0.5 if emission > 0 else 0.0,
        emission=emission,
        consensus=0.0,
        validator_trust=0.0,
        dividends=0.0,
        active=True,
        alpha_stake=0.0,
        total_stake=0.0,
        block_at_registration=block_at_registration,
    )


neuron_strategy = st.builds(
    _make_neuron,
    uid=st.integers(min_value=0, max_value=255),
    emission=st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    block_at_registration=st.integers(min_value=0, max_value=10_000_000),
)

neurons_list_strategy = st.lists(neuron_strategy, min_size=1, max_size=192)


# =============================================================================
# Property Tests
# =============================================================================


class TestDeregistrationRiskInvariants:
    """Property 1: Deregistration Risk Score Invariants."""

    @given(
        neurons=neurons_list_strategy,
        num_uids=st.integers(min_value=1, max_value=256),
        max_uids=st.integers(min_value=1, max_value=256),
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_all_scores_in_valid_range(
        self, neurons, num_uids, max_uids, recent_registrations
    ):
        """All risk scores must be in [0.0, 1.0]."""
        num_uids = min(num_uids, max_uids)

        risks = MetricsEngine.compute_deregistration_risk(
            neurons=neurons,
            current_block=CURRENT_BLOCK,
            immunity_period=IMMUNITY_PERIOD,
            recent_registrations_24h=recent_registrations,
            num_uids=num_uids,
            max_uids=max_uids,
        )

        for r in risks:
            assert 0.0 <= r.risk_score <= 1.0, f"Risk {r.risk_score} out of [0, 1]"

    @given(
        neurons=st.lists(
            st.builds(
                _make_neuron,
                uid=st.integers(min_value=0, max_value=255),
                emission=st.floats(min_value=0.0, max_value=100.0,
                                   allow_nan=False, allow_infinity=False),
                # Recently registered → immune
                block_at_registration=st.integers(
                    min_value=CURRENT_BLOCK - IMMUNITY_PERIOD + 1,
                    max_value=CURRENT_BLOCK,
                ),
            ),
            min_size=1, max_size=50,
        ),
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_immune_miners_always_zero_risk(self, neurons, recent_registrations):
        """Any miner within immunity period must have risk score exactly 0.0."""
        risks = MetricsEngine.compute_deregistration_risk(
            neurons=neurons,
            current_block=CURRENT_BLOCK,
            immunity_period=IMMUNITY_PERIOD,
            recent_registrations_24h=recent_registrations,
            num_uids=256,
            max_uids=256,
        )

        for r in risks:
            assert r.risk_score == 0.0, f"Immune miner has non-zero risk: {r.risk_score}"
            assert r.immune is True

    @given(
        neurons=st.lists(
            st.builds(
                _make_neuron,
                uid=st.integers(min_value=0, max_value=255),
                emission=st.floats(min_value=0.0, max_value=100.0,
                                   allow_nan=False, allow_infinity=False),
                # Registered long ago → NOT immune
                block_at_registration=st.integers(min_value=0, max_value=1_000_000),
            ),
            min_size=1, max_size=50,
        ),
        max_uids=st.integers(min_value=2, max_value=256),
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_non_full_subnet_all_zero_risk(self, neurons, max_uids, recent_registrations):
        """When subnet has empty slots (num_uids < max_uids), all miners get risk 0.0."""
        num_uids = min(len(neurons), max_uids - 1)
        assume(num_uids < max_uids)

        risks = MetricsEngine.compute_deregistration_risk(
            neurons=neurons,
            current_block=CURRENT_BLOCK,
            immunity_period=IMMUNITY_PERIOD,
            recent_registrations_24h=recent_registrations,
            num_uids=num_uids,
            max_uids=max_uids,
        )

        for r in risks:
            assert r.risk_score == 0.0, f"Non-full subnet has non-zero risk: {r.risk_score}"

    @given(
        emissions=st.lists(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=4, max_size=192,
        ).filter(lambda es: len(set(es)) == len(es)),  # unique emissions only
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_monotonicity_by_emission_rank(self, emissions, recent_registrations):
        """On a full subnet with unique emissions, higher emission → lower or equal risk."""
        # All non-immune (registered long ago), full subnet
        neurons = [
            _make_neuron(uid=i, emission=em, block_at_registration=100_000)
            for i, em in enumerate(emissions)
        ]

        risks = MetricsEngine.compute_deregistration_risk(
            neurons=neurons,
            current_block=CURRENT_BLOCK,
            immunity_period=IMMUNITY_PERIOD,
            recent_registrations_24h=recent_registrations,
            num_uids=256,
            max_uids=256,
        )

        # Match risk scores to neurons by UID
        risk_by_uid = {r.uid: r.risk_score for r in risks}
        paired = sorted(
            [(em, risk_by_uid[i]) for i, em in enumerate(emissions)],
            key=lambda x: x[0],
        )

        # Higher emission should have lower or equal risk
        for i in range(1, len(paired)):
            assert paired[i][1] <= paired[i - 1][1], (
                f"Monotonicity violated: emission {paired[i][0]} has risk {paired[i][1]} "
                f"> emission {paired[i-1][0]} with risk {paired[i-1][1]}"
            )
