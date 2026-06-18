"""Property tests for MetricsEngine.compute_price_trend."""

import sys
sys.path.insert(0, "lambda")

from hypothesis import given, strategies as st, assume
from src.processor.metrics import MetricsEngine


class TestPriceTrendProperties:
    """Property-based tests for compute_price_trend."""

    @given(st.lists(st.floats(min_value=0.001, max_value=100.0), min_size=2, max_size=200))
    def test_trend_bounded_by_price_extremes(self, prices):
        """Trend should be (last - first) / first."""
        result = MetricsEngine.compute_price_trend(prices)
        expected = (prices[-1] - prices[0]) / prices[0]
        assert abs(result["price_trend_7d"] - round(expected, 6)) < 1e-5

    @given(st.lists(st.floats(min_value=0.001, max_value=100.0), min_size=2, max_size=200))
    def test_volatility_non_negative(self, prices):
        """Volatility should always be >= 0."""
        result = MetricsEngine.compute_price_trend(prices)
        assert result["price_volatility_7d"] >= 0.0

    @given(st.lists(st.floats(min_value=0.001, max_value=100.0), min_size=2, max_size=200))
    def test_direction_consistent_with_trend(self, prices):
        """Direction should match trend sign with 5% threshold."""
        result = MetricsEngine.compute_price_trend(prices)
        if result["price_trend_7d"] > 0.05:
            assert result["trend_direction"] == "up"
        elif result["price_trend_7d"] < -0.05:
            assert result["trend_direction"] == "down"
        else:
            assert result["trend_direction"] == "stable"

    def test_empty_returns_stable(self):
        """Empty price list returns neutral defaults."""
        result = MetricsEngine.compute_price_trend([])
        assert result["price_trend_7d"] == 0.0
        assert result["price_volatility_7d"] == 0.0
        assert result["trend_direction"] == "stable"

    def test_single_price_returns_stable(self):
        """Single price returns neutral defaults."""
        result = MetricsEngine.compute_price_trend([0.05])
        assert result["trend_direction"] == "stable"

    def test_constant_prices_zero_volatility(self):
        """Constant prices should produce zero volatility."""
        result = MetricsEngine.compute_price_trend([0.05] * 100)
        assert result["price_trend_7d"] == 0.0
        assert result["price_volatility_7d"] == 0.0
        assert result["trend_direction"] == "stable"

    def test_monotone_increasing_positive_trend(self):
        """Monotonically increasing prices should have positive trend."""
        prices = [1.0 + 0.01 * i for i in range(100)]
        result = MetricsEngine.compute_price_trend(prices)
        assert result["price_trend_7d"] > 0
        assert result["trend_direction"] == "up"

    def test_monotone_decreasing_negative_trend(self):
        """Monotonically decreasing prices should have negative trend."""
        prices = [1.0 - 0.005 * i for i in range(100)]
        result = MetricsEngine.compute_price_trend(prices)
        assert result["price_trend_7d"] < 0
        assert result["trend_direction"] == "down"
