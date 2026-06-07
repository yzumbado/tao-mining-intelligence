"""Property tests for Stage 3 STRATEGIZE scoring and optimizer."""

import pytest
from hypothesis import given, strategies as st, assume, settings

from src.strategizer.scoring import (
    filter_opportunities,
    score_opportunity,
    evaluate_exits,
    _score_yield,
    _score_risk,
    _score_accessibility,
    _estimate_mining_yield,
    _estimate_validating_yield,
    DEFAULT_WEIGHTS,
)
from src.strategizer.optimizer import optimize_portfolio


# ---------------------------------------------------------------------------
# Strategy helpers for generating test data
# ---------------------------------------------------------------------------

def _ranking(netuid=1, net_tao_yield=10.0, real_apy_percent=50.0,
             self_mining_risk=0.0, competitive_density=0.1, **kwargs):
    base = {
        "netuid": netuid,
        "net_tao_yield": net_tao_yield,
        "real_apy_percent": real_apy_percent,
        "attractiveness_score": 0.5,
        "self_mining_risk": self_mining_risk,
        "concentration_risk": {"risk": 0.0, "tier": "healthy", "active_validators": 5},
        "competitive_density": competitive_density,
        "emission_trend": 0.0,
        "alpha_price": 0.1,
        "days_to_recoup": 1.0,
        "thirty_day_projection": 300.0,
    }
    base.update(kwargs)
    return base


def _research(gpu_required=False, vram_gb_estimate=None, open_source_miner=True,
              difficulty="trivial", research_confidence="high"):
    return {
        "gpu_required": gpu_required,
        "vram_gb_estimate": vram_gb_estimate,
        "open_source_miner": open_source_miner,
        "difficulty": difficulty,
        "research_confidence": research_confidence,
    }


def _profile(hardware=None, tao_available_stake=100.0, tao_available_registration=1.0,
             risk_tolerance="moderate", max_positions=3, prefer_passive=True):
    return {
        "hardware": hardware or [],
        "tao_available_stake": tao_available_stake,
        "tao_available_registration": tao_available_registration,
        "risk_tolerance": risk_tolerance,
        "max_positions": max_positions,
        "prefer_passive": prefer_passive,
        "excluded_subnets": [],
        "min_pool_liquidity_tao": 500.0,
    }


# ---------------------------------------------------------------------------
# Property: Yield score is bounded [0, 1] and monotonic
# ---------------------------------------------------------------------------

class TestYieldScoring:
    @given(yield_val=st.floats(min_value=0.0, max_value=10000.0),
           max_yield=st.floats(min_value=0.1, max_value=10000.0))
    @settings(max_examples=200)
    def test_yield_score_bounded(self, yield_val, max_yield):
        ranking = _ranking(net_tao_yield=yield_val)
        score = _score_yield(ranking, max_yield)
        assert 0.0 <= score <= 1.0

    def test_yield_score_monotonic(self):
        scores = [_score_yield(_ranking(net_tao_yield=y), 100.0) for y in [10, 30, 50, 70, 100]]
        assert scores == sorted(scores)

    def test_yield_score_max_equals_one(self):
        assert _score_yield(_ranking(net_tao_yield=100.0), 100.0) == 1.0

    def test_yield_score_zero_max_returns_zero(self):
        assert _score_yield(_ranking(net_tao_yield=50.0), 0.0) == 0.0


# ---------------------------------------------------------------------------
# Property: Risk score is bounded [0, 1]
# ---------------------------------------------------------------------------

class TestRiskScoring:
    @given(
        self_mining=st.floats(min_value=0.0, max_value=1.0),
        conc_risk=st.floats(min_value=0.0, max_value=1.0),
        emission_trend=st.floats(min_value=-0.01, max_value=0.01),
        alpha_price=st.floats(min_value=0.0, max_value=10.0),
    )
    @settings(max_examples=200)
    def test_risk_score_bounded(self, self_mining, conc_risk, emission_trend, alpha_price):
        ranking = _ranking(
            self_mining_risk=self_mining,
            concentration_risk={"risk": conc_risk, "tier": "healthy"},
            emission_trend=emission_trend,
            alpha_price=alpha_price,
        )
        score = _score_risk(ranking)
        assert 0.0 <= score <= 1.0

    def test_zero_risk_scores_one(self):
        ranking = _ranking(self_mining_risk=0.0, alpha_price=1.0, emission_trend=0.0)
        ranking["concentration_risk"] = {"risk": 0.0, "tier": "healthy"}
        assert _score_risk(ranking) == 1.0

    def test_max_risk_scores_low(self):
        ranking = _ranking(self_mining_risk=1.0, alpha_price=0.0, emission_trend=0.01)
        ranking["concentration_risk"] = {"risk": 1.0, "tier": "critical"}
        score = _score_risk(ranking)
        assert score < 0.2


# ---------------------------------------------------------------------------
# Property: Accessibility score bounded [0, 1]
# ---------------------------------------------------------------------------

class TestAccessibilityScoring:
    @given(
        difficulty=st.sampled_from(["trivial", "medium", "hard", "unknown"]),
        confidence=st.sampled_from(["high", "medium", "low", "none"]),
    )
    @settings(max_examples=100)
    def test_accessibility_bounded(self, difficulty, confidence):
        research = _research(difficulty=difficulty, research_confidence=confidence)
        score = _score_accessibility(research)
        assert 0.0 <= score <= 1.0

    def test_trivial_high_confidence_is_max(self):
        score = _score_accessibility(_research(difficulty="trivial", research_confidence="high"))
        assert score == 1.0

    def test_no_research_is_low(self):
        score = _score_accessibility({})
        assert score <= 0.4


# ---------------------------------------------------------------------------
# Property: Mining yield is non-negative and respects WTA rule
# ---------------------------------------------------------------------------

class TestMiningYield:
    def test_no_miner_returns_zero(self):
        ranking = _ranking(net_tao_yield=100.0)
        research = _research(open_source_miner=False)
        profile = _profile(hardware=[{"type": "RTX 4090", "vram_gb": 24}])
        assert _estimate_mining_yield(ranking, research, profile, 260.0) == 0.0

    def test_wta_hard_difficulty_returns_zero(self):
        """WTA subnet + hard difficulty → yield = 0 (can't compete)."""
        ranking = _ranking(net_tao_yield=100.0, competitive_density=0.005)  # WTA signal
        research = _research(difficulty="hard", gpu_required=True, vram_gb_estimate=24)
        profile = _profile(hardware=[{"type": "RTX 4090", "vram_gb": 24}])
        assert _estimate_mining_yield(ranking, research, profile, 260.0) == 0.0

    def test_wta_trivial_difficulty_returns_positive(self):
        """WTA subnet + trivial difficulty → can compete."""
        ranking = _ranking(net_tao_yield=100.0, competitive_density=0.005)
        research = _research(difficulty="trivial", gpu_required=False)
        profile = _profile(hardware=[{"type": "RTX 4090", "vram_gb": 24}])
        result = _estimate_mining_yield(ranking, research, profile, 260.0)
        assert result > 0.0

    def test_no_hardware_gpu_required_returns_zero(self):
        ranking = _ranking(net_tao_yield=100.0)
        research = _research(gpu_required=True, vram_gb_estimate=48)
        profile = _profile(hardware=[{"type": "RTX 4090", "vram_gb": 24}])  # Only 24GB
        assert _estimate_mining_yield(ranking, research, profile, 260.0) == 0.0

    @given(net_yield=st.floats(min_value=0.0, max_value=1000.0))
    @settings(max_examples=100)
    def test_mining_yield_non_negative(self, net_yield):
        ranking = _ranking(net_tao_yield=net_yield, competitive_density=0.1)
        research = _research(difficulty="trivial", gpu_required=False)
        profile = _profile(hardware=[{"type": "RTX 4090", "vram_gb": 24}])
        result = _estimate_mining_yield(ranking, research, profile, 260.0)
        assert result >= 0.0


# ---------------------------------------------------------------------------
# Property: Validating yield is non-negative and proportional to stake
# ---------------------------------------------------------------------------

class TestValidatingYield:
    @given(
        stake=st.floats(min_value=0.0, max_value=100000.0),
        apy=st.floats(min_value=0.0, max_value=5000.0),
    )
    @settings(max_examples=200)
    def test_validating_yield_non_negative(self, stake, apy):
        ranking = _ranking(real_apy_percent=apy)
        profile = _profile(tao_available_stake=stake)
        result = _estimate_validating_yield(ranking, profile)
        assert result >= 0.0

    def test_zero_stake_returns_zero(self):
        ranking = _ranking(real_apy_percent=100.0)
        profile = _profile(tao_available_stake=0.0)
        assert _estimate_validating_yield(ranking, profile) == 0.0

    def test_higher_apy_gives_higher_yield(self):
        profile = _profile(tao_available_stake=1000.0)
        low = _estimate_validating_yield(_ranking(real_apy_percent=10.0), profile)
        high = _estimate_validating_yield(_ranking(real_apy_percent=100.0), profile)
        assert high > low


# ---------------------------------------------------------------------------
# Property: Filter removes self-mining risk subnets for non-aggressive
# ---------------------------------------------------------------------------

class TestFiltering:
    def test_self_mining_filtered_for_conservative(self):
        rankings = [_ranking(netuid=1, self_mining_risk=0.5)]
        survivors, reasons = filter_opportunities(rankings, {}, _profile(risk_tolerance="conservative"))
        assert len(survivors) == 0
        assert reasons.get("self_mining_risk", 0) == 1

    def test_self_mining_kept_for_aggressive(self):
        rankings = [_ranking(netuid=1, self_mining_risk=0.5)]
        survivors, _ = filter_opportunities(rankings, {}, _profile(risk_tolerance="aggressive"))
        assert len(survivors) == 1

    def test_excluded_subnets_filtered(self):
        rankings = [_ranking(netuid=5), _ranking(netuid=10)]
        profile = _profile()
        profile["excluded_subnets"] = [5]
        survivors, reasons = filter_opportunities(rankings, {}, profile)
        assert len(survivors) == 1
        assert survivors[0]["netuid"] == 10


# ---------------------------------------------------------------------------
# Property: Optimizer respects max_positions constraint
# ---------------------------------------------------------------------------

class TestOptimizer:
    def test_respects_max_positions(self):
        scored = [
            {"netuid": i, "fitness_score": 0.9 - i * 0.1, "expected_daily_tao": 1.0,
             "expected_monthly_tao": 30.0, "entry_cost_tao": 0.3, "role": "validate",
             "rationale": "test", "scores": {"yield": 0.9, "risk": 0.9, "accessibility": 0.9, "efficiency": 0.9}}
            for i in range(10)
        ]
        profile = _profile(max_positions=2, tao_available_stake=1000.0)
        result = optimize_portfolio(scored, profile, DEFAULT_WEIGHTS)
        assert len(result["recommendations"]) <= 2

    def test_do_nothing_when_below_threshold(self):
        scored = [
            {"netuid": 1, "fitness_score": 0.1, "expected_daily_tao": 0.01,
             "expected_monthly_tao": 0.3, "entry_cost_tao": 0.5, "role": "validate",
             "rationale": "test", "scores": {"yield": 0.1, "risk": 0.1, "accessibility": 0.1, "efficiency": 0.1}}
        ]
        result = optimize_portfolio(scored, _profile(), DEFAULT_WEIGHTS)
        assert len(result["recommendations"]) == 0
        assert result["do_nothing_reason"] is not None

    def test_empty_input_returns_do_nothing(self):
        result = optimize_portfolio([], _profile(), DEFAULT_WEIGHTS)
        assert len(result["recommendations"]) == 0


# ---------------------------------------------------------------------------
# Property: Exit recommendations
# ---------------------------------------------------------------------------

class TestExitRecommendations:
    def test_apy_collapse_triggers_exit(self):
        positions = [{"netuid": 1, "role": "validate", "entry_apy_percent": 100.0}]
        rankings = [_ranking(netuid=1, real_apy_percent=30.0)]  # 70% drop
        exits = evaluate_exits(positions, rankings, DEFAULT_WEIGHTS)
        assert len(exits) == 1
        assert exits[0]["urgency"] == "high"

    def test_self_mining_emergence_triggers_exit(self):
        positions = [{"netuid": 1, "role": "validate", "entry_self_mining_risk": 0.0}]
        rankings = [_ranking(netuid=1, self_mining_risk=0.5)]
        exits = evaluate_exits(positions, rankings, DEFAULT_WEIGHTS)
        assert len(exits) == 1
        assert "Self-mining" in exits[0]["reason"]

    def test_missing_subnet_triggers_high_urgency_exit(self):
        positions = [{"netuid": 99, "role": "mine"}]
        rankings = [_ranking(netuid=1)]  # SN99 not in rankings
        exits = evaluate_exits(positions, rankings, DEFAULT_WEIGHTS)
        assert len(exits) == 1
        assert exits[0]["urgency"] == "high"

    def test_no_degradation_no_exit(self):
        positions = [{"netuid": 1, "role": "validate", "entry_apy_percent": 50.0, "entry_self_mining_risk": 0.0}]
        rankings = [_ranking(netuid=1, real_apy_percent=50.0, self_mining_risk=0.0)]
        exits = evaluate_exits(positions, rankings, DEFAULT_WEIGHTS)
        assert len(exits) == 0


# ---------------------------------------------------------------------------
# Property: score_opportunity produces bounded fitness
# ---------------------------------------------------------------------------

class TestScoreOpportunity:
    @given(
        net_yield=st.floats(min_value=0.1, max_value=500.0),
        apy=st.floats(min_value=1.0, max_value=3000.0),
    )
    @settings(max_examples=200)
    def test_fitness_bounded(self, net_yield, apy):
        ranking = _ranking(net_tao_yield=net_yield, real_apy_percent=apy)
        research = _research(difficulty="trivial", gpu_required=False)
        profile = _profile(tao_available_stake=1000.0)
        result = score_opportunity(ranking, research, profile, 500.0, 10.0, 260.0, dict(DEFAULT_WEIGHTS))
        assert 0.0 <= result["fitness_score"] <= 1.0

    def test_output_has_required_fields(self):
        ranking = _ranking()
        research = _research()
        profile = _profile(tao_available_stake=500.0)
        result = score_opportunity(ranking, research, profile, 100.0, 10.0, 260.0, dict(DEFAULT_WEIGHTS))
        assert "netuid" in result
        assert "role" in result
        assert "fitness_score" in result
        assert "expected_daily_tao" in result
        assert "rationale" in result
        assert "scores" in result
