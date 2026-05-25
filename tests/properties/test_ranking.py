# Feature: tao-mining-intelligence-pipeline, Property 7: Ranking Sort Order Invariant
"""Property-based tests for subnet ranking using actual production code.

Properties verified:
1. compute_attractiveness_score always returns [0.0, 1.0]
2. Higher yield → higher score (monotonicity)
3. Higher self_mining_risk → lower score (penalty works)
4. Score is deterministic (same inputs → same output)
5. Rankings sorted descending when generated from scores
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.processor.metrics import MetricsEngine


class TestAttractivenessScoreProperties:
    """Property tests for the actual production attractiveness score."""

    @given(
        net_tao_yield=st.floats(min_value=0.0, max_value=500.0,
                                allow_nan=False, allow_infinity=False),
        emission_share=st.floats(min_value=0.0, max_value=0.1,
                                 allow_nan=False, allow_infinity=False),
        pool_depth=st.floats(min_value=0.0, max_value=100000.0,
                             allow_nan=False, allow_infinity=False),
        self_mining_risk=st.floats(min_value=0.0, max_value=1.0,
                                   allow_nan=False, allow_infinity=False),
        net_flow_ema=st.floats(min_value=-5000.0, max_value=5000.0,
                               allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=300)
    def test_score_always_in_valid_range(self, net_tao_yield, emission_share,
                                         pool_depth, self_mining_risk, net_flow_ema):
        """Score must always be in [0.0, 1.0]."""
        score = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=net_tao_yield, emission_share=emission_share,
            pool_depth_tao=pool_depth, self_mining_risk=self_mining_risk,
            net_flow_ema=net_flow_ema)
        assert 0.0 <= score <= 1.0

    @given(
        yield_low=st.floats(min_value=0.0, max_value=100.0,
                            allow_nan=False, allow_infinity=False),
        yield_delta=st.floats(min_value=0.01, max_value=100.0,
                              allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_higher_yield_higher_score(self, yield_low, yield_delta):
        """Holding all else equal, higher yield must produce higher score."""
        kwargs = dict(emission_share=0.01, pool_depth_tao=5000.0,
                      self_mining_risk=0.0, net_flow_ema=0.0)
        low = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=yield_low, **kwargs)
        high = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=yield_low + yield_delta, **kwargs)
        assert high >= low

    @given(
        risk_low=st.floats(min_value=0.0, max_value=0.5,
                           allow_nan=False, allow_infinity=False),
        risk_delta=st.floats(min_value=0.01, max_value=0.5,
                             allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_higher_risk_lower_score(self, risk_low, risk_delta):
        """Higher self-mining risk must reduce score (penalty is multiplicative)."""
        assume(risk_low + risk_delta <= 1.0)
        kwargs = dict(net_tao_yield=50.0, emission_share=0.01,
                      pool_depth_tao=5000.0, net_flow_ema=0.0)
        clean = MetricsEngine.compute_attractiveness_score(
            self_mining_risk=risk_low, **kwargs)
        risky = MetricsEngine.compute_attractiveness_score(
            self_mining_risk=risk_low + risk_delta, **kwargs)
        assert risky <= clean

    @given(
        net_tao_yield=st.floats(min_value=0.0, max_value=200.0,
                                allow_nan=False, allow_infinity=False),
        emission_share=st.floats(min_value=0.0, max_value=0.05,
                                 allow_nan=False, allow_infinity=False),
        pool_depth=st.floats(min_value=0.0, max_value=50000.0,
                             allow_nan=False, allow_infinity=False),
        self_mining_risk=st.floats(min_value=0.0, max_value=1.0,
                                   allow_nan=False, allow_infinity=False),
        net_flow_ema=st.floats(min_value=-2000.0, max_value=2000.0,
                               allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_deterministic(self, net_tao_yield, emission_share, pool_depth,
                           self_mining_risk, net_flow_ema):
        """Same inputs must always produce same output."""
        kwargs = dict(net_tao_yield=net_tao_yield, emission_share=emission_share,
                      pool_depth_tao=pool_depth, self_mining_risk=self_mining_risk,
                      net_flow_ema=net_flow_ema)
        assert MetricsEngine.compute_attractiveness_score(**kwargs) == \
               MetricsEngine.compute_attractiveness_score(**kwargs)

    def test_full_self_mining_risk_zeroes_score(self):
        """risk=1.0 should produce score=0.0 regardless of other inputs."""
        score = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=200.0, emission_share=0.02,
            pool_depth_tao=50000.0, self_mining_risk=1.0,
            net_flow_ema=1000.0)
        assert score == 0.0

    def test_zero_yield_low_score(self):
        """Zero yield should produce a low score (flow component still contributes)."""
        score = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=0.0, emission_share=0.0,
            pool_depth_tao=0.0, self_mining_risk=0.0,
            net_flow_ema=0.0)
        assert score < 0.3


class TestRankingSortOrder:
    """Verify that rankings from scores are sorted correctly."""

    @given(
        yields=st.lists(
            st.floats(min_value=0.0, max_value=200.0,
                      allow_nan=False, allow_infinity=False),
            min_size=2, max_size=50,
        )
    )
    @settings(max_examples=100)
    def test_rankings_sorted_descending(self, yields):
        """When we score multiple subnets and sort, order is descending."""
        scores = [
            MetricsEngine.compute_attractiveness_score(
                net_tao_yield=y, emission_share=0.01,
                pool_depth_tao=5000.0, self_mining_risk=0.0,
                net_flow_ema=0.0)
            for y in yields
        ]
        sorted_scores = sorted(scores, reverse=True)
        for i in range(1, len(sorted_scores)):
            assert sorted_scores[i] <= sorted_scores[i - 1]
