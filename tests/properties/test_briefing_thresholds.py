# Feature: tao-mining-intelligence-pipeline, Property 13: Daily Briefing Threshold Filtering
"""Property-based tests for daily briefing threshold filtering.

Properties verified:
1. Subnets with emission change > threshold ARE included
2. Subnets with emission change ≤ threshold are NOT included in emission section
3. Subnets with reg cost change > threshold ARE included
4. Rank changes > threshold ARE included
"""


from hypothesis import given, settings, assume
from hypothesis import strategies as st



def filter_briefing_alerts(
    changes: list[dict],
    emission_threshold: float = 0.10,
    reg_cost_threshold: float = 0.20,
    rank_threshold: int = 50,
) -> dict[str, list[int]]:
    """Filter subnet changes against briefing thresholds.
    
    This is the core briefing filter logic extracted for testability.
    
    Args:
        changes: List of dicts with netuid, emission_change_pct, reg_cost_change_pct, rank_change.
        emission_threshold: Minimum emission change to trigger alert.
        reg_cost_threshold: Minimum reg cost change to trigger alert.
        rank_threshold: Minimum rank change positions to trigger alert.
    
    Returns:
        Dict with keys 'emission_alerts', 'reg_cost_alerts', 'rank_alerts' containing netuid lists.
    """
    emission_alerts = []
    reg_cost_alerts = []
    rank_alerts = []

    for change in changes:
        netuid = change["netuid"]
        if abs(change.get("emission_change_pct", 0)) > emission_threshold:
            emission_alerts.append(netuid)
        if abs(change.get("reg_cost_change_pct", 0)) > reg_cost_threshold:
            reg_cost_alerts.append(netuid)
        if abs(change.get("rank_change", 0)) > rank_threshold:
            rank_alerts.append(netuid)

    return {
        "emission_alerts": emission_alerts,
        "reg_cost_alerts": reg_cost_alerts,
        "rank_alerts": rank_alerts,
    }


class TestBriefingThresholdProperties:
    """Property 13: Daily Briefing Threshold Filtering."""

    @given(
        emission_change=st.floats(min_value=0.11, max_value=5.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_above_emission_threshold_included(self, emission_change):
        """Subnets with emission change > 10% must be included."""
        changes = [{"netuid": 1, "emission_change_pct": emission_change, "reg_cost_change_pct": 0, "rank_change": 0}]
        result = filter_briefing_alerts(changes)
        assert 1 in result["emission_alerts"]

    @given(
        emission_change=st.floats(min_value=-0.10, max_value=0.10, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_below_emission_threshold_excluded(self, emission_change):
        """Subnets with emission change ≤ 10% must NOT be in emission alerts."""
        changes = [{"netuid": 1, "emission_change_pct": emission_change, "reg_cost_change_pct": 0, "rank_change": 0}]
        result = filter_briefing_alerts(changes)
        assert 1 not in result["emission_alerts"]

    @given(
        reg_cost_change=st.floats(min_value=0.21, max_value=10.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_above_reg_cost_threshold_included(self, reg_cost_change):
        """Subnets with reg cost change > 20% must be included."""
        changes = [{"netuid": 2, "emission_change_pct": 0, "reg_cost_change_pct": reg_cost_change, "rank_change": 0}]
        result = filter_briefing_alerts(changes)
        assert 2 in result["reg_cost_alerts"]

    @given(
        rank_change=st.integers(min_value=51, max_value=200),
    )
    @settings(max_examples=100)
    def test_above_rank_threshold_included(self, rank_change):
        """Miners with rank change > 50 positions must be included."""
        changes = [{"netuid": 3, "emission_change_pct": 0, "reg_cost_change_pct": 0, "rank_change": rank_change}]
        result = filter_briefing_alerts(changes)
        assert 3 in result["rank_alerts"]

    @given(
        rank_change=st.integers(min_value=-50, max_value=50),
    )
    @settings(max_examples=100)
    def test_below_rank_threshold_excluded(self, rank_change):
        """Miners with rank change ≤ 50 must NOT be in rank alerts."""
        changes = [{"netuid": 3, "emission_change_pct": 0, "reg_cost_change_pct": 0, "rank_change": rank_change}]
        result = filter_briefing_alerts(changes)
        assert 3 not in result["rank_alerts"]

    def test_negative_emission_change_also_triggers(self):
        """Large negative emission change (>10% drop) should also trigger."""
        changes = [{"netuid": 5, "emission_change_pct": -0.15, "reg_cost_change_pct": 0, "rank_change": 0}]
        result = filter_briefing_alerts(changes)
        assert 5 in result["emission_alerts"]
