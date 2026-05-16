# Feature: tao-mining-intelligence-pipeline, Property 11: AMM Slippage Estimation
"""Property-based tests for AMM slippage estimation.

Properties verified:
1. Slippage in [0.0, 1.0)
2. Monotonically increasing with sell amount
3. Zero sell → zero slippage
4. Approaches 1.0 as sell amount → infinity relative to pool
"""

import sys

from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, "lambda/src")

from processor.metrics import MetricsEngine


class TestSlippageProperties:
    """Property 11: AMM Slippage Estimation."""

    @given(
        sell_amount=st.floats(min_value=0.0, max_value=1e12, allow_nan=False, allow_infinity=False),
        alpha_price=st.floats(min_value=0.0001, max_value=1000.0, allow_nan=False, allow_infinity=False),
        pool_tao=st.floats(min_value=0.01, max_value=1e9, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_slippage_in_valid_range(self, sell_amount, alpha_price, pool_tao):
        """Slippage must be in [0.0, 1.0]."""
        result = MetricsEngine._estimate_slippage(sell_amount, alpha_price, pool_tao)
        assert 0.0 <= result <= 1.0, f"Slippage {result} out of range"

    @given(
        alpha_price=st.floats(min_value=0.001, max_value=100.0, allow_nan=False, allow_infinity=False),
        pool_tao=st.floats(min_value=100.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_zero_sell_produces_zero_slippage(self, alpha_price, pool_tao):
        """Selling 0 tokens should produce 0 slippage."""
        result = MetricsEngine._estimate_slippage(0.0, alpha_price, pool_tao)
        assert result == 0.0

    @given(
        small_amount=st.floats(min_value=1.0, max_value=10000.0, allow_nan=False, allow_infinity=False),
        multiplier=st.floats(min_value=1.5, max_value=100.0, allow_nan=False, allow_infinity=False),
        alpha_price=st.floats(min_value=0.001, max_value=10.0, allow_nan=False, allow_infinity=False),
        pool_tao=st.floats(min_value=100.0, max_value=1e6, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=200)
    def test_monotonically_increasing_with_sell_amount(
        self, small_amount, multiplier, alpha_price, pool_tao
    ):
        """Larger sell amounts should produce equal or higher slippage.
        
        Note: We use amounts >= 1.0 and multiplier >= 1.5 to avoid floating
        point noise at very small values where slippage is effectively zero.
        """
        large_amount = small_amount * multiplier

        small_slippage = MetricsEngine._estimate_slippage(small_amount, alpha_price, pool_tao)
        large_slippage = MetricsEngine._estimate_slippage(large_amount, alpha_price, pool_tao)

        assert large_slippage >= small_slippage - 1e-9, (
            f"Monotonicity violated: sell {small_amount} → slippage {small_slippage}, "
            f"sell {large_amount} → slippage {large_slippage}"
        )

    def test_large_sell_relative_to_pool_high_slippage(self):
        """Selling a large amount relative to pool should produce high slippage."""
        # Sell 10x the pool's alpha reserves
        pool_tao = 1000.0
        alpha_price = 0.01  # pool_alpha = 1000/0.01 = 100,000
        sell_amount = 1_000_000.0  # 10x pool alpha

        result = MetricsEngine._estimate_slippage(sell_amount, alpha_price, pool_tao)
        assert result > 0.8, f"Large sell should have high slippage, got {result}"

    def test_tiny_sell_relative_to_pool_low_slippage(self):
        """Selling a tiny amount relative to pool should produce near-zero slippage."""
        pool_tao = 100_000.0
        alpha_price = 0.01
        sell_amount = 0.1  # Tiny relative to pool

        result = MetricsEngine._estimate_slippage(sell_amount, alpha_price, pool_tao)
        assert result < 0.001, f"Tiny sell should have near-zero slippage, got {result}"

    def test_zero_pool_returns_max_slippage(self):
        """Zero pool liquidity should return 1.0 (can't sell)."""
        result = MetricsEngine._estimate_slippage(100.0, 0.01, 0.0)
        assert result == 1.0

    def test_zero_price_returns_max_slippage(self):
        """Zero alpha price should return 1.0 (can't sell)."""
        result = MetricsEngine._estimate_slippage(100.0, 0.0, 1000.0)
        assert result == 1.0
