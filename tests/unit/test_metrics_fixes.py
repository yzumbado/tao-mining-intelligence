"""Unit tests for metrics data interpretation fixes.

Tests the bugs found in live data analysis (2026-05-18):
1. Deregistration risk uses active field incorrectly (should use num_uids/max_uids)
2. Competitive density uses active field incorrectly (should use earning miners)
3. Attractiveness score ceiling at 0.950 (yield cap too low)
"""


from src.models.schemas import Neuron
from src.processor.metrics import MetricsEngine


def _make_neuron(uid: int, emission: float = 0.0, incentive: float = 0.0,
                 dividends: float = 0.0, active: bool = False,
                 block_at_registration: int = 1000000, stake: float = 0.0) -> Neuron:
    """Helper to create a Neuron with minimal required fields."""
    return Neuron(
        uid=uid,
        hotkey=f"5{'A' * 47}{uid:03d}",
        coldkey=f"5{'B' * 47}{uid:03d}",
        stake=stake,
        incentive=incentive,
        emission=emission,
        consensus=0.0,
        validator_trust=0.0,
        dividends=dividends,
        active=active,
        alpha_stake=0.0,
        total_stake=0.0,
        block_at_registration=block_at_registration,
    )


class TestDeregistrationRiskActiveBug:
    """Tests that deregistration risk works correctly when active=False but subnet is full."""

    def test_full_subnet_with_inactive_miners_has_nonzero_risk(self):
        """Bug: All miners have active=False but subnet IS full (256/256 registered).
        The old code uses sum(active) for occupancy → thinks subnet has empty slots → risk=0.
        Fix: Use num_uids >= max_uids to determine fullness.
        """
        # 10 miners: all active=False, all non-immune, varying emissions
        neurons = [
            _make_neuron(i, emission=float(i + 1), incentive=0.5, active=False,
                         block_at_registration=100000)  # registered long ago → not immune
            for i in range(10)
        ]
        current_block = 5000000  # way past immunity
        immunity_period = 7200

        risks = MetricsEngine.compute_deregistration_risk(
            neurons=neurons,
            current_block=current_block,
            immunity_period=immunity_period,
            recent_registrations_24h=5,
            num_uids=256,
            max_uids=256,
        )

        # On a full subnet with non-immune miners, SOME should have risk > 0
        risk_scores = [r.risk_score for r in risks]
        assert max(risk_scores) > 0, (
            f"Full subnet (256/256) with non-immune miners should have risk > 0, "
            f"got all zeros: {risk_scores}"
        )

    def test_not_full_subnet_all_zero_risk(self):
        """When num_uids < max_uids, subnet has empty slots → no deregistration risk."""
        neurons = [
            _make_neuron(i, emission=float(i + 1), incentive=0.5, active=False,
                         block_at_registration=100000)
            for i in range(10)
        ]

        risks = MetricsEngine.compute_deregistration_risk(
            neurons=neurons,
            current_block=5000000,
            immunity_period=7200,
            recent_registrations_24h=5,
            num_uids=200,
            max_uids=256,
        )

        risk_scores = [r.risk_score for r in risks]
        assert all(r == 0.0 for r in risk_scores), (
            f"Non-full subnet (200/256) should have all zero risk, got: {risk_scores}"
        )

    def test_immune_miners_zero_risk_on_full_subnet(self):
        """Immune miners get risk=0 even on a full subnet."""
        neurons = [
            _make_neuron(i, emission=float(i + 1), incentive=0.5, active=False,
                         block_at_registration=4999000)  # registered recently → immune
            for i in range(10)
        ]

        risks = MetricsEngine.compute_deregistration_risk(
            neurons=neurons,
            current_block=5000000,  # only 1000 blocks since reg < 7200 immunity
            immunity_period=7200,
            recent_registrations_24h=10,
            num_uids=256,
            max_uids=256,
        )

        risk_scores = [r.risk_score for r in risks]
        assert all(r == 0.0 for r in risk_scores), (
            f"Immune miners on full subnet should have zero risk, got: {risk_scores}"
        )


class TestCompetitiveDensityActiveBug:
    """Tests that competitive density works when miners have active=False but are earning."""

    def test_earning_miners_with_active_false_have_nonzero_density(self):
        """Bug: Miners earn (emission > 0) but have active=False.
        Old code counts active miners → 0 → density = 0.
        Fix: Count earning miners (emission > 0) instead.
        """
        neurons = [
            _make_neuron(i, emission=10.0, incentive=0.5, active=False)
            for i in range(50)
        ]

        density = MetricsEngine.compute_competitive_density(neurons)

        assert density > 0, (
            f"50 earning miners (emission>0) should produce density > 0, got {density}"
        )

    def test_no_earning_miners_zero_density(self):
        """When no miners earn, density should be 0."""
        neurons = [
            _make_neuron(i, emission=0.0, incentive=0.0, active=False)
            for i in range(50)
        ]

        density = MetricsEngine.compute_competitive_density(neurons)
        assert density == 0.0


class TestAttractivenessScoreCeiling:
    """Tests that attractiveness score differentiates high-yield subnets."""

    def test_higher_yield_gets_higher_score(self):
        """Bug: Both 85 TAO/day and 18 TAO/day score 0.950 due to cap at 5 TAO/day.
        Fix: Raise normalization ceiling so scores differentiate.
        """
        from src.processor.metrics import MetricsEngine

        score_high = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=85.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=0.0)

        score_low = MetricsEngine.compute_attractiveness_score(
            net_tao_yield=18.0, emission_share=0.01,
            pool_depth_tao=5000.0, self_mining_risk=0.0,
            net_flow_ema=0.0)

        assert score_high > score_low, (
            f"85 TAO/day ({score_high:.4f}) should score higher than "
            f"18 TAO/day ({score_low:.4f})"
        )
