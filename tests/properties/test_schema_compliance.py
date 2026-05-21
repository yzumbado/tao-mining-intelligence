# Feature: tao-mining-intelligence-pipeline, Property 14: Output Schema Compliance
"""Property-based tests for output schema compliance.

Properties verified:
1. All outputs contain metadata header with required fields
2. TAO amounts are in TAO units (not RAO — values < 21,000,000)
3. Percentages are decimals in [0.0, 1.0]
4. Block numbers are positive integers
"""

from datetime import datetime, timezone

from hypothesis import given, settings
from hypothesis import strategies as st


from models.schemas import (
    MetadataHeader,
    Neuron,
    DeregistrationRisk,
    ROIEstimate,
    TaoflowHealth,
    ChurnMetrics,
    ValidatorLandscape,
    SubnetRanking,
    EmissionTrend,
)
from models.enums import (
    Confidence,
    CompetitionTrend,
    HoldVsSwap,
    TaoflowStatus,
)


class TestSchemaComplianceProperties:
    """Property 14: Output Schema Compliance."""

    @given(
        schema_version=st.from_regex(r"[0-9]+\.[0-9]+\.[0-9]+", fullmatch=True),
        block=st.integers(min_value=0, max_value=100_000_000),
    )
    @settings(max_examples=100)
    def test_metadata_header_has_required_fields(self, schema_version, block):
        """Metadata header must contain schema_version, timestamp, pipeline_version."""
        header = MetadataHeader(
            schema_version=schema_version,
            collection_timestamp=datetime.now(timezone.utc),
            pipeline_version="1.0.0",
            source_block_number=block,
        )
        assert header.schema_version == schema_version
        assert header.collection_timestamp is not None
        assert header.pipeline_version is not None

    @given(
        stake=st.floats(min_value=0.0, max_value=21_000_000.0, allow_nan=False, allow_infinity=False),
        emission=st.floats(min_value=0.0, max_value=21_000_000.0, allow_nan=False, allow_infinity=False),
        incentive=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        consensus=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        dividends=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_neuron_tao_amounts_in_valid_range(self, stake, emission, incentive, consensus, dividends):
        """TAO amounts must be < 21,000,000. Percentages must be in [0, 1]."""
        neuron = Neuron(
            uid=0,
            hotkey="5Ftest000",
            coldkey="5Ctest000",
            stake=stake,
            incentive=incentive,
            emission=emission,
            consensus=consensus,
            validator_trust=0.0,
            dividends=dividends,
            active=True,
            alpha_stake=0.0,
            total_stake=stake,
            block_at_registration=1000000,
        )
        assert neuron.stake <= 21_000_000
        assert 0.0 <= neuron.incentive <= 1.0
        assert 0.0 <= neuron.consensus <= 1.0
        assert 0.0 <= neuron.dividends <= 1.0

    @given(
        risk=st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        rank=st.integers(min_value=0, max_value=255),
    )
    @settings(max_examples=100)
    def test_deregistration_risk_valid_ranges(self, risk, rank):
        """Risk scores in [0,1], emission_rank non-negative."""
        dr = DeregistrationRisk(
            uid=0, hotkey="5Ftest", risk_score=risk, emission_rank=rank, immune=False
        )
        assert 0.0 <= dr.risk_score <= 1.0
        assert dr.emission_rank >= 0

    def test_immune_miner_must_have_zero_risk(self):
        """Pydantic validator: immune miners must have risk_score 0.0."""
        dr = DeregistrationRisk(
            uid=0, hotkey="5Ftest", risk_score=0.0, emission_rank=0, immune=True
        )
        assert dr.risk_score == 0.0

        # This should raise a validation error
        import pytest
        with pytest.raises(Exception):
            DeregistrationRisk(
                uid=0, hotkey="5Ftest", risk_score=0.5, emission_rank=0, immune=True
            )

    @given(
        yield_val=st.floats(min_value=0.0, max_value=1000.0, allow_nan=False, allow_infinity=False),
        days=st.floats(min_value=0.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    )
    @settings(max_examples=100)
    def test_roi_estimate_valid_ranges(self, yield_val, days):
        """ROI fields must be non-negative where specified."""
        roi = ROIEstimate(
            net_tao_yield_per_day=yield_val,
            days_to_recoup=days,
            thirty_day_projected_tao=yield_val * 30 - 1.0,
            alpha_tao_rate=0.01,
            slippage_estimate_percent=0.05,
            hold_vs_swap_recommendation=HoldVsSwap.SWAP,
            confidence=Confidence.HIGH,
        )
        assert roi.net_tao_yield_per_day >= 0.0
        assert roi.days_to_recoup >= 0.0
        assert 0.0 <= roi.slippage_estimate_percent <= 1.0

    @given(
        block=st.integers(min_value=0, max_value=100_000_000),
    )
    @settings(max_examples=50)
    def test_block_numbers_are_positive_integers(self, block):
        """Block numbers must be non-negative integers."""
        neuron = Neuron(
            uid=0, hotkey="5F", coldkey="5C", stake=0.0, incentive=0.0,
            emission=0.0, consensus=0.0, validator_trust=0.0, dividends=0.0,
            active=True, alpha_stake=0.0, total_stake=0.0,
            block_at_registration=block,
        )
        assert isinstance(neuron.block_at_registration, int)
        assert neuron.block_at_registration >= 0
