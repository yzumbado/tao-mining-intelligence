# Feature: tao-mining-intelligence-pipeline, Property 10: Rental Profitability Computation
"""Property-based tests for rental profitability analysis.

Properties verified:
1. rent_vs_buy_multiplier = net_tao_yield / (daily_cost / tao_price)
2. rental_profitable iff multiplier > 1.0
3. break_even_tao_price = daily_cost / net_tao_yield
4. daily_profit = (yield × price) - cost
"""

import sys

from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, "lambda/src")

from processor.metrics import MetricsEngine


SAMPLE_PRICING = {
    "vast.ai": {"RTX 4090": 0.35, "A100 40GB": 0.90},
    "runpod": {"RTX 4090": 0.40, "A100 80GB": 1.10},
}


class TestRentalProfitabilityProperties:
    """Property 10: Rental Profitability Computation."""

    @given(
        net_yield=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        tao_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_rent_vs_buy_formula(self, net_yield, tao_price):
        """rent_vs_buy = net_tao_yield / (daily_cost / tao_price)."""
        result = MetricsEngine.compute_rental_profitability(
            net_tao_yield_per_day=net_yield,
            tao_usd_price=tao_price,
            hardware_tier="CONSUMER_GPU",
            cloud_pricing=SAMPLE_PRICING,
        )

        if result.cheapest_viable_config is None:
            return  # No pricing data

        daily_cost = result.daily_rental_cost_usd
        tao_buyable = daily_cost / tao_price
        expected_multiplier = net_yield / tao_buyable if tao_buyable > 0 else 0.0

        assert abs(result.rent_vs_buy_multiplier - expected_multiplier) < 1e-6, (
            f"Multiplier {result.rent_vs_buy_multiplier} != expected {expected_multiplier}"
        )

    @given(
        net_yield=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        tao_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_profitable_iff_multiplier_above_one(self, net_yield, tao_price):
        """rental_profitable must be True iff rent_vs_buy_multiplier > 1.0."""
        result = MetricsEngine.compute_rental_profitability(
            net_tao_yield_per_day=net_yield,
            tao_usd_price=tao_price,
            hardware_tier="CONSUMER_GPU",
            cloud_pricing=SAMPLE_PRICING,
        )

        if result.cheapest_viable_config is None:
            return

        assert result.rental_profitable == (result.rent_vs_buy_multiplier > 1.0)

    @given(
        net_yield=st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
        tao_price=st.floats(min_value=10.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_break_even_formula(self, net_yield, tao_price):
        """break_even_tao_price = daily_cost / net_tao_yield."""
        result = MetricsEngine.compute_rental_profitability(
            net_tao_yield_per_day=net_yield,
            tao_usd_price=tao_price,
            hardware_tier="CONSUMER_GPU",
            cloud_pricing=SAMPLE_PRICING,
        )

        if result.cheapest_viable_config is None:
            return

        expected_break_even = result.daily_rental_cost_usd / net_yield
        assert abs(result.break_even_tao_price_usd - expected_break_even) < 1e-6

    @given(
        net_yield=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        tao_price=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_daily_profit_formula(self, net_yield, tao_price):
        """daily_profit = (yield × price) - cost."""
        result = MetricsEngine.compute_rental_profitability(
            net_tao_yield_per_day=net_yield,
            tao_usd_price=tao_price,
            hardware_tier="CONSUMER_GPU",
            cloud_pricing=SAMPLE_PRICING,
        )

        if result.cheapest_viable_config is None:
            return

        expected_profit = (net_yield * tao_price) - result.daily_rental_cost_usd
        assert abs(result.daily_profit_usd - expected_profit) < 1e-6

    def test_cpu_only_not_profitable(self):
        """CPU_ONLY tier should return not profitable (no GPU needed)."""
        result = MetricsEngine.compute_rental_profitability(
            net_tao_yield_per_day=1.0,
            tao_usd_price=300.0,
            hardware_tier="CPU_ONLY",
            cloud_pricing=SAMPLE_PRICING,
        )
        assert not result.rental_profitable

    def test_no_pricing_data_not_profitable(self):
        """Empty pricing should return not profitable."""
        result = MetricsEngine.compute_rental_profitability(
            net_tao_yield_per_day=1.0,
            tao_usd_price=300.0,
            hardware_tier="CONSUMER_GPU",
            cloud_pricing={},
        )
        assert not result.rental_profitable
