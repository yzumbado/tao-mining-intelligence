# Feature: tao-mining-intelligence-pipeline, Property 1: Deregistration Risk Score Invariants
"""Property-based tests for deregistration risk scoring.

Properties verified:
1. All risk scores are in [0.0, 1.0]
2. Immune miners always get risk score 0.0
3. Non-full subnets: all miners get risk score 0.0
4. On full subnets, risk scores are monotonically non-increasing as emission rank improves
"""

import sys

import pytest
from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, "lambda/src")

from processor.metrics import compute_deregistration_risk


# =============================================================================
# Hypothesis Strategies (Data Generators)
# =============================================================================

# A single miner's data for the risk function
miner_data_strategy = st.fixed_dictionaries({
    "uid": st.integers(min_value=0, max_value=255),
    "emission": st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
    "block_at_registration": st.integers(min_value=0, max_value=10_000_000),
    "is_immune": st.booleans(),
})

# List of miners (1 to 192 miners, matching max miner slots)
miners_list_strategy = st.lists(miner_data_strategy, min_size=1, max_size=192)


# =============================================================================
# Property Tests
# =============================================================================


class TestDeregistrationRiskInvariants:
    """Property 1: Deregistration Risk Score Invariants."""

    @given(
        miners=miners_list_strategy,
        total_slots=st.integers(min_value=1, max_value=256),
        occupied_slots=st.integers(min_value=1, max_value=256),
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_all_scores_in_valid_range(
        self, miners, total_slots, occupied_slots, recent_registrations
    ):
        """All risk scores must be in [0.0, 1.0]."""
        occupied_slots = min(occupied_slots, total_slots)

        emissions = [m["emission"] for m in miners]
        is_immune = [m["is_immune"] for m in miners]

        risks = compute_deregistration_risk(
            emissions=emissions,
            is_immune=is_immune,
            total_slots=total_slots,
            occupied_slots=occupied_slots,
            recent_registrations_24h=recent_registrations,
        )

        for risk in risks:
            assert 0.0 <= risk <= 1.0, f"Risk {risk} out of range [0, 1]"

    @given(
        miners=miners_list_strategy,
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_immune_miners_always_zero_risk(self, miners, recent_registrations):
        """Any miner within immunity period must have risk score exactly 0.0."""
        # Force all miners to be immune
        is_immune = [True] * len(miners)
        emissions = [m["emission"] for m in miners]

        risks = compute_deregistration_risk(
            emissions=emissions,
            is_immune=is_immune,
            total_slots=256,
            occupied_slots=256,  # Full subnet
            recent_registrations_24h=recent_registrations,
        )

        for risk in risks:
            assert risk == 0.0, f"Immune miner has non-zero risk: {risk}"

    @given(
        miners=miners_list_strategy,
        total_slots=st.integers(min_value=2, max_value=256),
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_non_full_subnet_all_zero_risk(self, miners, total_slots, recent_registrations):
        """When subnet has empty slots, all miners get risk 0.0."""
        # Ensure occupied < total (at least one empty slot)
        occupied_slots = min(len(miners), total_slots - 1)
        assume(occupied_slots < total_slots)

        emissions = [m["emission"] for m in miners]
        is_immune = [False] * len(miners)  # None immune, but doesn't matter

        risks = compute_deregistration_risk(
            emissions=emissions,
            is_immune=is_immune,
            total_slots=total_slots,
            occupied_slots=occupied_slots,
            recent_registrations_24h=recent_registrations,
        )

        for risk in risks:
            assert risk == 0.0, f"Non-full subnet has non-zero risk: {risk}"

    @given(
        emissions=st.lists(
            st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=4,
            max_size=192,
        ),
        recent_registrations=st.integers(min_value=0, max_value=50),
    )
    @settings(max_examples=200)
    def test_monotonicity_by_emission_rank(self, emissions, recent_registrations):
        """On a full subnet, higher emission → lower or equal risk (monotonically non-increasing)."""
        # All non-immune, full subnet
        is_immune = [False] * len(emissions)

        risks = compute_deregistration_risk(
            emissions=emissions,
            is_immune=is_immune,
            total_slots=256,
            occupied_slots=256,
            recent_registrations_24h=recent_registrations,
        )

        # Sort by emission ascending, risks should be non-increasing
        # (lowest emission = highest risk)
        paired = sorted(zip(emissions, risks), key=lambda x: x[0])

        for i in range(1, len(paired)):
            # Higher emission should have lower or equal risk
            assert paired[i][1] <= paired[i - 1][1] or paired[i][0] == paired[i - 1][0], (
                f"Monotonicity violated: emission {paired[i][0]} has risk {paired[i][1]} "
                f"> emission {paired[i-1][0]} with risk {paired[i-1][1]}"
            )
