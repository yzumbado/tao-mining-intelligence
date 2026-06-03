# Feature: tao-mining-intelligence-pipeline, Property: Self-Mining Detection
"""Property-based tests for self-mining risk detection.

Properties verified:
1. Result always in [0.0, 1.0]
2. A subnet with many distinct miners and validators → low risk
3. A subnet with 1 miner, 1 validator, same coldkey → high risk
4. Empty neuron list → risk 0.0 (no data, no flag)
5. Signals list is always a subset of known signals
"""

from hypothesis import given, settings, assume
from hypothesis import strategies as st

from processor.metrics import MetricsEngine
from models.schemas import Neuron


def _make_neuron(uid: int, hotkey: str, coldkey: str, incentive: float,
                 emission: float, dividends: float, stake: float = 0.0,
                 alpha_stake: float = 0.0) -> Neuron:
    """Helper to build a Neuron with minimal required fields."""
    return Neuron(
        uid=uid, hotkey=hotkey, coldkey=coldkey,
        stake=stake, incentive=incentive, emission=emission,
        consensus=0.0, validator_trust=0.0, dividends=dividends,
        active=True, alpha_stake=alpha_stake, total_stake=stake,
        block_at_registration=0,
    )


# Strategy: generate a list of neurons with varied properties
neuron_strategy = st.lists(
    st.fixed_dictionaries({
        "uid": st.integers(min_value=0, max_value=255),
        "coldkey_id": st.integers(min_value=0, max_value=10),
        "incentive": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "emission": st.floats(min_value=0.0, max_value=100.0, allow_nan=False, allow_infinity=False),
        "dividends": st.floats(min_value=0.0, max_value=1.0, allow_nan=False, allow_infinity=False),
        "stake": st.floats(min_value=0.0, max_value=100000.0, allow_nan=False, allow_infinity=False),
    }),
    min_size=0,
    max_size=64,
)


def _build_neurons_from_dicts(neuron_dicts: list[dict]) -> list[Neuron]:
    """Convert hypothesis-generated dicts to Neuron objects with unique UIDs."""
    neurons = []
    for i, d in enumerate(neuron_dicts):
        coldkey = f"5Cold{d['coldkey_id']:04d}"
        neurons.append(_make_neuron(
            uid=i,
            hotkey=f"5Hot{i:04d}",
            coldkey=coldkey,
            incentive=d["incentive"],
            emission=d["emission"],
            dividends=d["dividends"],
            stake=d["stake"],
            alpha_stake=d["stake"] * 0.5,
        ))
    return neurons


KNOWN_SIGNALS = {
    "single_or_no_earning_miner",
    "single_validator",
    "coldkey_overlap",
    "low_neuron_diversity",
}


class TestSelfMiningRiskProperties:
    """Property tests for compute_self_mining_risk."""

    @given(neuron_dicts=neuron_strategy)
    @settings(max_examples=200)
    def test_risk_always_in_valid_range(self, neuron_dicts):
        """Risk score must be in [0.0, 1.0]."""
        neurons = _build_neurons_from_dicts(neuron_dicts)
        result = MetricsEngine.compute_self_mining_risk(neurons)
        assert 0.0 <= result["risk_score"] <= 1.0

    @given(neuron_dicts=neuron_strategy)
    @settings(max_examples=200)
    def test_signals_are_known(self, neuron_dicts):
        """All reported signals must be from the known set."""
        neurons = _build_neurons_from_dicts(neuron_dicts)
        result = MetricsEngine.compute_self_mining_risk(neurons)
        assert set(result["signals"]).issubset(KNOWN_SIGNALS)

    def test_empty_neurons_returns_zero(self):
        """No neurons → no data to flag, risk 0."""
        result = MetricsEngine.compute_self_mining_risk([])
        assert result["risk_score"] == 0.0
        assert result["signals"] == []

    def test_classic_self_mining_pattern_high_risk(self):
        """1 miner + 1 validator + same coldkey = maximum risk."""
        neurons = [
            _make_neuron(0, "5HotMiner", "5ColdOwner", incentive=1.0,
                         emission=50.0, dividends=0.0, stake=0.0),
            _make_neuron(1, "5HotValidator", "5ColdOwner", incentive=0.0,
                         emission=10.0, dividends=1.0, stake=100000.0,
                         alpha_stake=100000.0),
        ]
        result = MetricsEngine.compute_self_mining_risk(neurons)
        assert result["risk_score"] >= 0.8, f"Classic self-mining got only {result['risk_score']}"
        assert "single_or_no_earning_miner" in result["signals"]
        assert "single_validator" in result["signals"]
        assert "coldkey_overlap" in result["signals"]

    def test_healthy_subnet_low_risk(self):
        """Many miners, many validators, diverse coldkeys → low risk."""
        neurons = []
        # 10 miners with distinct coldkeys
        for i in range(10):
            neurons.append(_make_neuron(
                i, f"5HotMiner{i}", f"5ColdMiner{i}",
                incentive=0.5, emission=5.0, dividends=0.0,
            ))
        # 5 validators with distinct coldkeys
        for i in range(5):
            neurons.append(_make_neuron(
                10 + i, f"5HotVal{i}", f"5ColdVal{i}",
                incentive=0.0, emission=2.0, dividends=0.2,
                stake=50000.0, alpha_stake=50000.0,
            ))
        result = MetricsEngine.compute_self_mining_risk(neurons)
        assert result["risk_score"] <= 0.15, f"Healthy subnet got {result['risk_score']}"

    def test_single_miner_multiple_validators_medium_risk(self):
        """1 miner but multiple independent validators → partial risk."""
        neurons = [
            _make_neuron(0, "5HotMiner", "5ColdMiner", incentive=1.0,
                         emission=50.0, dividends=0.0),
        ]
        for i in range(5):
            neurons.append(_make_neuron(
                1 + i, f"5HotVal{i}", f"5ColdVal{i}",
                incentive=0.0, emission=2.0, dividends=0.2,
                stake=50000.0, alpha_stake=50000.0,
            ))
        result = MetricsEngine.compute_self_mining_risk(neurons)
        # Single miner with multiple validators = WTA subnet, NOT self-mining
        # Signal 1 only fires when validators <= 2 (indicating no real competition)
        assert "single_or_no_earning_miner" not in result["signals"]
        assert "single_validator" not in result["signals"]
        assert "coldkey_overlap" not in result["signals"]

    @given(
        num_miners=st.integers(min_value=5, max_value=50),
        num_validators=st.integers(min_value=3, max_value=20),
    )
    @settings(max_examples=100)
    def test_diverse_subnet_never_high_risk(self, num_miners, num_validators):
        """A subnet with many distinct participants should never score > 0.35."""
        neurons = []
        for i in range(num_miners):
            neurons.append(_make_neuron(
                i, f"5HotM{i}", f"5ColdM{i}",
                incentive=0.5, emission=5.0, dividends=0.0,
            ))
        for i in range(num_validators):
            neurons.append(_make_neuron(
                num_miners + i, f"5HotV{i}", f"5ColdV{i}",
                incentive=0.0, emission=2.0, dividends=0.2,
                stake=50000.0, alpha_stake=50000.0,
            ))
        result = MetricsEngine.compute_self_mining_risk(neurons)
        assert result["risk_score"] <= 0.35
