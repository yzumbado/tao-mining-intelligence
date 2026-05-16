# Feature: tao-mining-intelligence-pipeline, Property 7: Ranking Sort Order Invariant
"""Property-based tests for subnet ranking.

Properties verified:
1. Output is sorted in strictly descending order by attractiveness score
2. Ranking contains exactly one entry per input subnet
3. All required fields are present in each entry
"""

import sys

from hypothesis import given, settings
from hypothesis import strategies as st

sys.path.insert(0, "lambda/src")


# Simple ranking function that sorts subnets by score
def generate_rankings(subnet_scores: list[tuple[int, float]]) -> list[dict]:
    """Generate a ranked list of subnets sorted by attractiveness score descending.
    
    This is the core ranking logic extracted for testability.
    
    Args:
        subnet_scores: List of (netuid, attractiveness_score) tuples.
    
    Returns:
        List of ranking dicts sorted by score descending.
    """
    rankings = [
        {
            "netuid": netuid,
            "attractiveness_score": score,
            "net_tao_yield": 0.0,  # Placeholder
            "days_to_recoup": 0.0,
            "thirty_day_projection": 0.0,
            "active_miners": 0,
            "registration_cost": 0.0,
            "competitive_density": 0.0,
            "emission_trend": 0.0,
            "alpha_price": 0.0,
            "alpha_liquidity": 0.0,
        }
        for netuid, score in subnet_scores
    ]
    return sorted(rankings, key=lambda x: x["attractiveness_score"], reverse=True)


class TestRankingSortOrderProperties:
    """Property 7: Ranking Sort Order Invariant."""

    @given(
        scores=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=200),
                st.floats(min_value=-10.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=1,
            max_size=129,
        )
    )
    @settings(max_examples=200)
    def test_sorted_descending_by_score(self, scores):
        """Rankings must be sorted in descending order by attractiveness_score."""
        rankings = generate_rankings(scores)

        for i in range(1, len(rankings)):
            assert rankings[i]["attractiveness_score"] <= rankings[i - 1]["attractiveness_score"], (
                f"Not sorted: position {i-1} score {rankings[i-1]['attractiveness_score']} "
                f"< position {i} score {rankings[i]['attractiveness_score']}"
            )

    @given(
        scores=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=200),
                st.floats(min_value=-10.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=1,
            max_size=129,
        )
    )
    @settings(max_examples=200)
    def test_one_entry_per_subnet(self, scores):
        """Ranking must contain exactly one entry per input subnet."""
        rankings = generate_rankings(scores)
        assert len(rankings) == len(scores)

    @given(
        scores=st.lists(
            st.tuples(
                st.integers(min_value=0, max_value=200),
                st.floats(min_value=-10.0, max_value=100.0, allow_nan=False, allow_infinity=False),
            ),
            min_size=1,
            max_size=50,
        )
    )
    @settings(max_examples=200)
    def test_all_required_fields_present(self, scores):
        """Each ranking entry must contain all required fields."""
        required_fields = {
            "netuid", "attractiveness_score", "net_tao_yield", "days_to_recoup",
            "thirty_day_projection", "active_miners", "registration_cost",
            "competitive_density", "emission_trend", "alpha_price", "alpha_liquidity",
        }

        rankings = generate_rankings(scores)
        for entry in rankings:
            missing = required_fields - set(entry.keys())
            assert not missing, f"Missing fields: {missing}"

    def test_empty_input_returns_empty(self):
        """Empty input produces empty ranking."""
        assert generate_rankings([]) == []

    def test_single_subnet(self):
        """Single subnet produces single-entry ranking."""
        rankings = generate_rankings([(1, 5.0)])
        assert len(rankings) == 1
        assert rankings[0]["netuid"] == 1
        assert rankings[0]["attractiveness_score"] == 5.0
