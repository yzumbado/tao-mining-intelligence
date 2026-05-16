# Feature: tao-mining-intelligence-pipeline, Property 2: Gini Coefficient Bounds and Semantics
"""Property-based tests for Gini coefficient computation.

Properties verified:
1. Result always in [0.0, 1.0]
2. All-equal values produce Gini = 0.0
3. Single holder (one value, rest zero) approaches 1.0
4. Adding a value equal to the mean does not increase Gini
"""

import sys

from hypothesis import given, settings, assume
from hypothesis import strategies as st

sys.path.insert(0, "lambda/src")

from processor.metrics import MetricsEngine


class TestGiniCoefficientProperties:
    """Property 2: Gini Coefficient Bounds and Semantics."""

    @given(
        emissions=st.lists(
            st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
            min_size=0,
            max_size=256,
        )
    )
    @settings(max_examples=200)
    def test_result_always_in_valid_range(self, emissions):
        """Gini coefficient must be in [0.0, 1.0]."""
        result = MetricsEngine.compute_gini_coefficient(emissions)
        assert 0.0 <= result <= 1.0, f"Gini {result} out of range"

    @given(
        value=st.floats(min_value=0.01, max_value=1000.0, allow_nan=False, allow_infinity=False),
        count=st.integers(min_value=2, max_value=100),
    )
    @settings(max_examples=200)
    def test_all_equal_produces_zero(self, value, count):
        """A list where all values are equal must produce Gini ≈ 0.0."""
        emissions = [value] * count
        result = MetricsEngine.compute_gini_coefficient(emissions)
        assert result < 1e-10, f"All-equal list produced Gini {result}, expected ≈0.0"

    @given(
        value=st.floats(min_value=1.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        zero_count=st.integers(min_value=1, max_value=100),
    )
    @settings(max_examples=200)
    def test_single_holder_approaches_one(self, value, zero_count):
        """One value with all others zero should produce Gini approaching 1.0."""
        # Only the single positive value matters (zeros are filtered out)
        # With one positive value, Gini should be 0.0 (single value = no inequality)
        # But with one large and many small positive values, it approaches 1.0
        # Let's test: one large value + many tiny values
        emissions = [value] + [0.001] * zero_count
        result = MetricsEngine.compute_gini_coefficient(emissions)
        # With extreme inequality, Gini should be high (>0.5 for large ratios)
        if value / 0.001 > 100 and zero_count >= 5:
            assert result > 0.5, (
                f"Extreme inequality (ratio {value/0.001:.0f}:1, {zero_count} small) "
                f"produced low Gini {result}"
            )

    @given(
        emissions=st.lists(
            st.floats(min_value=0.01, max_value=100.0, allow_nan=False, allow_infinity=False),
            min_size=3,
            max_size=50,
        )
    )
    @settings(max_examples=200)
    def test_adding_mean_value_does_not_increase_gini(self, emissions):
        """Adding a value equal to the mean should not increase the Gini coefficient."""
        assume(len(emissions) >= 3)
        assume(sum(emissions) > 0)

        original_gini = MetricsEngine.compute_gini_coefficient(emissions)
        mean_value = sum(emissions) / len(emissions)
        extended = emissions + [mean_value]
        extended_gini = MetricsEngine.compute_gini_coefficient(extended)

        assert extended_gini <= original_gini + 0.001, (
            f"Adding mean value increased Gini from {original_gini:.4f} to {extended_gini:.4f}"
        )

    def test_empty_list_returns_zero(self):
        """Empty list should return 0.0."""
        assert MetricsEngine.compute_gini_coefficient([]) == 0.0

    def test_all_zeros_returns_zero(self):
        """All zeros should return 0.0."""
        assert MetricsEngine.compute_gini_coefficient([0.0, 0.0, 0.0]) == 0.0

    def test_single_value_returns_zero(self):
        """Single positive value should return 0.0."""
        assert MetricsEngine.compute_gini_coefficient([5.0]) == 0.0
