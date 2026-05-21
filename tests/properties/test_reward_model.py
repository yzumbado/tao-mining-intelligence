# Feature: tao-mining-intelligence-pipeline, Property 3: Reward Distribution Model Classification
"""Property-based tests for reward distribution model detection.

Properties verified:
1. Top-3 > 70% → WINNER_TAKES_ALL
2. Gini < 0.5 AND top-3 ≤ 70% → PROPORTIONAL
3. Classification is deterministic (same input → same output)
4. top_3_concentration = sum(top_3) / sum(all)
"""


from hypothesis import given, settings, assume
from hypothesis import strategies as st


from processor.metrics import MetricsEngine
from models.enums import RewardModel


class TestRewardModelProperties:
    """Property 3: Reward Distribution Model Classification Consistency."""

    @given(
        emissions=st.lists(
            st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=0,
            max_size=200,
        )
    )
    @settings(max_examples=200)
    def test_classification_is_deterministic(self, emissions):
        """Same emission array must always produce the same classification."""
        result1 = MetricsEngine.detect_reward_distribution_model(emissions)
        result2 = MetricsEngine.detect_reward_distribution_model(emissions)
        assert result1 == result2

    @given(
        emissions=st.lists(
            st.floats(min_value=0.001, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=200,
        )
    )
    @settings(max_examples=200)
    def test_top_3_concentration_formula(self, emissions):
        """top_3_concentration must equal sum(top_3) / sum(all) for active emissions."""
        active = [e for e in emissions if e > 0]
        assume(len(active) >= 3)
        assume(sum(active) > 0)

        model, gini, top_3 = MetricsEngine.detect_reward_distribution_model(emissions)

        sorted_desc = sorted(active, reverse=True)
        expected_top_3 = sum(sorted_desc[:3]) / sum(active)

        assert abs(top_3 - expected_top_3) < 1e-10, (
            f"top_3_concentration {top_3} != expected {expected_top_3}"
        )

    def test_extreme_wta_classified_correctly(self):
        """One miner with 90% of emission → WTA."""
        emissions = [90.0] + [1.0] * 10  # Top 1 has 90/100 = 90%
        model, gini, top_3 = MetricsEngine.detect_reward_distribution_model(emissions)
        assert model == RewardModel.WINNER_TAKES_ALL
        assert top_3 > 0.70

    def test_equal_distribution_classified_proportional(self):
        """All miners earning equally → PROPORTIONAL."""
        emissions = [10.0] * 50
        model, gini, top_3 = MetricsEngine.detect_reward_distribution_model(emissions)
        assert model == RewardModel.PROPORTIONAL
        assert gini < 0.5

    def test_fewer_than_3_active_is_unknown(self):
        """Fewer than 3 active miners → UNKNOWN."""
        emissions = [10.0, 5.0, 0.0, 0.0]  # Only 2 active
        model, gini, top_3 = MetricsEngine.detect_reward_distribution_model(emissions)
        assert model == RewardModel.UNKNOWN

    @given(
        emissions=st.lists(
            st.floats(min_value=0.001, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=200,
        )
    )
    @settings(max_examples=200)
    def test_gini_in_valid_range(self, emissions):
        """Gini coefficient in result must be in [0.0, 1.0]."""
        active = [e for e in emissions if e > 0]
        assume(len(active) >= 3)

        model, gini, top_3 = MetricsEngine.detect_reward_distribution_model(emissions)
        assert 0.0 <= gini <= 1.0
        assert 0.0 <= top_3 <= 1.0
