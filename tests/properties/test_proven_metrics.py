# Feature: tao-mining-intelligence-pipeline, Property: Proven Ecosystem Metrics
"""Property-based tests for proven ecosystem metrics.

Properties verified:
1. Real 1D APY: always finite, non-negative when emission > 0
2. Net TAO Flow EMA: bounded, monotone response to consistent flows
3. Attractiveness score: [0, 1], self-mining penalty reduces score
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from src.processor.metrics import MetricsEngine
from src.models.schemas import Neuron


def _make_neuron(uid: int, coldkey: str = "5Cold", hotkey: str = "5Hot",
                 incentive: float = 0.0, emission: float = 0.0,
                 dividends: float = 0.0, stake: float = 0.0,
                 alpha_stake: float = 0.0, validator_trust: float = 0.5) -> Neuron:
    return Neuron(
        uid=uid, hotkey=f"{hotkey}{uid}", coldkey=f"{coldkey}{uid}",
        stake=stake, incentive=incentive, emission=emission,
        consensus=0.0, validator_trust=validator_trust, dividends=dividends,
        active=True, alpha_stake=alpha_stake, total_stake=stake,
        block_at_registration=0,
    )


class TestRealAPYProperties:
    """Real 1D APY computed from actual emission snapshots."""

    @given(
        total_emission=st.floats(min_value=0.0, max_value=10000.0,
                                 allow_nan=False, allow_infinity=False),
        pool_tao=st.floats(min_value=100.0, max_value=1e6,
                           allow_nan=False, allow_infinity=False),
        alpha_price=st.floats(min_value=0.001, max_value=10.0,
                              allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_apy_always_finite_and_non_negative(self, total_emission, pool_tao, alpha_price):
        """APY must be finite and >= 0 when inputs are valid."""
        result = MetricsEngine.compute_real_apy(total_emission, pool_tao, alpha_price)
        assert result >= 0.0
        assert result != float("inf")

    def test_zero_emission_gives_zero_apy(self):
        assert MetricsEngine.compute_real_apy(0.0, 1000.0, 0.05) == 0.0

    def test_low_pool_gives_zero_apy(self):
        """Pool below threshold returns 0 (insufficient data guard)."""
        assert MetricsEngine.compute_real_apy(100.0, 1.0, 0.05) == 0.0

    def test_higher_emission_higher_apy(self):
        low = MetricsEngine.compute_real_apy(10.0, 1000.0, 0.01)
        high = MetricsEngine.compute_real_apy(20.0, 1000.0, 0.01)
        assert high > low


class TestNetTaoFlowProperties:
    """Net TAO Flow with 30-day EMA."""

    @given(
        stakes=st.lists(
            st.floats(min_value=0.0, max_value=1e9,
                      allow_nan=False, allow_infinity=False),
            min_size=0, max_size=60,
        )
    )
    @settings(max_examples=200)
    def test_flow_result_always_valid(self, stakes):
        """Flow result must have valid structure."""
        result = MetricsEngine.compute_net_tao_flow(stakes)
        assert "net_flow" in result
        assert "ema_flow" in result
        assert "days_of_data" in result
        assert result["days_of_data"] == len(stakes)

    def test_empty_history_returns_zero(self):
        result = MetricsEngine.compute_net_tao_flow([])
        assert result["net_flow"] == 0.0
        assert result["ema_flow"] == 0.0

    def test_single_day_returns_zero_flow(self):
        result = MetricsEngine.compute_net_tao_flow([1000.0])
        assert result["net_flow"] == 0.0

    def test_consistent_inflow_positive_ema(self):
        """Monotonically increasing stake → positive EMA flow."""
        stakes = [1000.0 + i * 100 for i in range(30)]
        result = MetricsEngine.compute_net_tao_flow(stakes)
        assert result["ema_flow"] > 0.0
        assert result["net_flow"] > 0.0

    def test_consistent_outflow_negative_ema(self):
        """Monotonically decreasing stake → negative EMA flow."""
        stakes = [10000.0 - i * 100 for i in range(30)]
        result = MetricsEngine.compute_net_tao_flow(stakes)
        assert result["ema_flow"] < 0.0

    @given(
        base=st.floats(min_value=100.0, max_value=1e6,
                       allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_flat_stake_zero_flow(self, base):
        """Constant stake → zero flow."""
        stakes = [base] * 10
        result = MetricsEngine.compute_net_tao_flow(stakes)
        assert abs(result["net_flow"]) < 1e-10
        assert abs(result["ema_flow"]) < 1e-10


class TestVTrustSurfacing:
    """VTrust should appear in validator landscape."""

    def test_vtrust_in_landscape(self):
        validators = [
            _make_neuron(i, dividends=0.2, stake=1000.0, alpha_stake=1000.0,
                         emission=5.0, validator_trust=0.8 + i * 0.02)
            for i in range(5)
        ]
        result = MetricsEngine.compute_validator_landscape(validators, 1.0)
        assert hasattr(result, "avg_vtrust")
        assert hasattr(result, "min_vtrust")
        assert result.avg_vtrust > 0.0
        assert result.min_vtrust > 0.0

    def test_zero_vtrust_validators(self):
        validators = [
            _make_neuron(i, dividends=0.2, stake=1000.0, alpha_stake=1000.0,
                         emission=5.0, validator_trust=0.0)
            for i in range(3)
        ]
        result = MetricsEngine.compute_validator_landscape(validators, 1.0)
        assert result.avg_vtrust == 0.0
        assert result.min_vtrust == 0.0


class TestRedesignedAttractivenessScore:
    """Risk-adjusted attractiveness score."""

    def test_score_in_valid_range(self):
        score = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=50.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=100.0)
        assert 0.0 <= score <= 1.0

    def test_self_mining_penalty_reduces_score(self):
        clean = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=50.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=100.0)
        risky = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=50.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.9,
            net_flow_ema=100.0)
        assert risky < clean

    def test_higher_yield_higher_score(self):
        low = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=10.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=100.0)
        high = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=100.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=100.0)
        assert high > low

    def test_negative_flow_reduces_score(self):
        positive = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=50.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=500.0)
        negative = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=50.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=-500.0)
        assert positive > negative

    def test_thin_pool_reduces_score(self):
        deep = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=50.0, emission_share=0.01,
            pool_depth_tao=50000.0, self_mining_risk=0.0,
            net_flow_ema=100.0)
        thin = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=50.0, emission_share=0.01,
            pool_depth_tao=100.0, self_mining_risk=0.0,
            net_flow_ema=100.0)
        assert deep > thin

    @given(
        net_tao_yield=st.floats(min_value=0.0, max_value=500.0,
                                allow_nan=False, allow_infinity=False),
        self_mining_risk=st.floats(min_value=0.0, max_value=1.0,
                                   allow_nan=False, allow_infinity=False),
        pool_depth=st.floats(min_value=0.0, max_value=1e6,
                             allow_nan=False, allow_infinity=False),
        flow=st.floats(min_value=-10000.0, max_value=10000.0,
                       allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_score_always_bounded(self, net_tao_yield, self_mining_risk, pool_depth, flow):
        score = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=net_tao_yield, emission_share=0.01,
            pool_depth_tao=pool_depth, self_mining_risk=self_mining_risk,
            net_flow_ema=flow)
        assert 0.0 <= score <= 1.0
