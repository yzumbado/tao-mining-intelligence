# Feature: tao-mining-intelligence-pipeline, Property 5: Taoflow Health Status Detection
"""Property-based tests for Taoflow health detection.

Properties verified:
1. <3 consecutive negative days → HEALTHY
2. 3-6 consecutive negative days → DECLINING
3. 7+ negative days AND >25% emission decline → DEATH_SPIRAL_RISK
4. 7+ negative days but ≤25% emission decline → DECLINING (not death spiral)
"""


from hypothesis import given, settings, assume
from hypothesis import strategies as st


from src.processor.metrics import MetricsEngine
from src.models.enums import TaoflowStatus


class TestTaoflowHealthProperties:
    """Property 5: Taoflow Health Status Detection."""

    @given(
        stake_history=st.lists(
            st.floats(min_value=100.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=30,
        ),
        emission_history=st.lists(
            st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=2,
            max_size=30,
        ),
    )
    @settings(max_examples=200)
    def test_status_is_always_valid_enum(self, stake_history, emission_history):
        """Status must always be one of HEALTHY, DECLINING, or DEATH_SPIRAL_RISK."""
        result = MetricsEngine.compute_taoflow_health(stake_history, emission_history)
        assert result.status in (
            TaoflowStatus.HEALTHY,
            TaoflowStatus.DECLINING,
            TaoflowStatus.DEATH_SPIRAL_RISK,
        )
        assert result.consecutive_negative_days >= 0

    @given(
        base_stake=st.floats(min_value=1000.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
        increases=st.lists(
            st.floats(min_value=0.1, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=5,
            max_size=15,
        ),
    )
    @settings(max_examples=200)
    def test_all_positive_flow_is_healthy(self, base_stake, increases):
        """If stake is always increasing, status must be HEALTHY."""
        # Build monotonically increasing stake history
        stake_history = [base_stake]
        for inc in increases:
            stake_history.append(stake_history[-1] + inc)

        emission_history = [100.0] * len(stake_history)

        result = MetricsEngine.compute_taoflow_health(stake_history, emission_history)
        assert result.status == TaoflowStatus.HEALTHY
        assert result.consecutive_negative_days == 0

    @given(
        base_stake=st.floats(min_value=10000.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
        decreases=st.lists(
            st.floats(min_value=0.1, max_value=50.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=6,
        ),
    )
    @settings(max_examples=200)
    def test_3_to_6_negative_days_is_declining(self, base_stake, decreases):
        """3-6 consecutive negative flow days → DECLINING."""
        assume(3 <= len(decreases) <= 6)

        # Build decreasing stake history
        stake_history = [base_stake]
        for dec in decreases:
            stake_history.append(stake_history[-1] - dec)

        # Emission stays stable (no >25% decline)
        emission_history = [100.0] * (len(stake_history) + 2)

        result = MetricsEngine.compute_taoflow_health(stake_history, emission_history)
        assert result.status == TaoflowStatus.DECLINING
        assert result.consecutive_negative_days >= 3

    @given(
        base_stake=st.floats(min_value=10000.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_7_plus_negative_with_emission_decline_is_death_spiral(self, base_stake):
        """7+ negative days AND >25% emission decline → DEATH_SPIRAL_RISK."""
        # 8 days of declining stake
        stake_history = [base_stake - i * 10 for i in range(9)]

        # Emission declines by >25% over the period
        emission_history = [100.0, 95.0, 90.0, 85.0, 80.0, 75.0, 70.0, 65.0, 60.0]
        # 100 → 60 = 40% decline > 25%

        result = MetricsEngine.compute_taoflow_health(stake_history, emission_history)
        assert result.status == TaoflowStatus.DEATH_SPIRAL_RISK

    @given(
        base_stake=st.floats(min_value=10000.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_7_plus_negative_without_emission_decline_is_declining(self, base_stake):
        """7+ negative days but ≤25% emission decline → DECLINING (not death spiral)."""
        # 8 days of declining stake
        stake_history = [base_stake - i * 10 for i in range(9)]

        # Emission stays relatively stable (only 10% decline, well under 25%)
        emission_history = [100.0, 99.0, 98.0, 97.0, 96.0, 95.0, 94.0, 93.0, 90.0]

        result = MetricsEngine.compute_taoflow_health(stake_history, emission_history)
        assert result.status == TaoflowStatus.DECLINING
        assert result.consecutive_negative_days >= 7
