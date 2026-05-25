"""Pydantic v2 data models for the TAO Mining Intelligence Pipeline.

Conventions:
- TAO for token amounts (not RAO)
- Percentages as decimals [0.0, 1.0]
- Block numbers as positive integers
"""

from datetime import datetime
from typing import Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from src.models.enums import (
    Confidence,
    CompetitionTrend,
    EntryBarrierLevel,
    HardwareTier,
    HoldVsSwap,
    MiningStyle,
    RewardModel,
    SubnetCategory,
    TaoflowStatus,
)


# =============================================================================
# Shared Metadata
# =============================================================================


class MetadataHeader(BaseModel):
    """Universal metadata header included in every pipeline output.

    This is the canonical metadata model referenced by Property 14 (Output Schema Compliance).
    All outputs must include these fields.
    """

    schema_version: str = "1.0.0"
    collection_timestamp: datetime
    pipeline_version: str = "1.0.0"
    source_block_number: Optional[int] = Field(default=None, ge=0)


class SnapshotMetadata(BaseModel):
    """Extended metadata header for raw snapshot outputs.

    Extends MetadataHeader with optional subnet-specific fields.
    """

    schema_version: str = "1.0.0"
    collection_timestamp: datetime
    pipeline_version: str = "1.0.0"
    source_block_number: Optional[int] = Field(default=None, ge=0)
    netuid: Optional[int] = Field(default=None, ge=0)
    subnet_name: Optional[str] = None


class DerivedMetadata(BaseModel):
    """Metadata header for derived/computed outputs."""

    schema_version: str = "1.0.0"
    computation_timestamp: datetime
    pipeline_version: str = "1.0.0"
    netuid: int = Field(ge=0)
    source_snapshot_date: str  # ISO date string YYYY-MM-DD


# =============================================================================
# Raw Metagraph Snapshot
# =============================================================================


class Neuron(BaseModel):
    """A single neuron (miner or validator) in a subnet metagraph.
    
    Field mapping from Bittensor SDK v10.3.2:
    - S → stake (TAO)
    - I → incentive [0,1]
    - E → emission (alpha tokens per tempo)
    - C → consensus [0,1]
    - Tv → validator_trust [0,1]
    - D → dividends [0,1]
    - AS → alpha_stake
    - TS → total_stake (TAO + alpha combined)
    
    NOTE: R (rank) and T (trust) were removed in SDK v10. 
    Rank can be derived from incentive ordering.
    Trust is no longer directly available.
    
    NOTE: blocks_since_last_step is a SUBNET-LEVEL scalar in SDK v10,
    NOT per-neuron. It's stored in the snapshot metadata, not per neuron.
    """

    uid: int = Field(ge=0, le=4096)
    hotkey: str
    coldkey: str
    stake: float = Field(ge=0.0, description="Stake in TAO (from S field)")
    incentive: float = Field(ge=0.0, le=1.0, description="Incentive share [0,1] (from I field)")
    emission: float = Field(ge=0.0, description="Emission in alpha tokens per tempo (from E field)")
    consensus: float = Field(ge=0.0, le=1.0, description="Consensus score [0,1] (from C field)")
    validator_trust: float = Field(ge=0.0, le=1.0, description="Validator trust [0,1] (from Tv field)")
    dividends: float = Field(ge=0.0, le=1.0, description="Dividends share [0,1] (from D field)")
    active: bool
    alpha_stake: float = Field(default=0.0, ge=0.0, description="Alpha token stake (from AS field)")
    total_stake: float = Field(default=0.0, ge=0.0, description="Total stake TAO+alpha (from TS field)")
    block_at_registration: int = Field(ge=0)

    @property
    def is_validator(self) -> bool:
        """A neuron is a validator if it has non-zero dividends."""
        return self.dividends > 0


class MetagraphData(BaseModel):
    """Data payload for a metagraph snapshot."""

    neurons: list[Neuron]
    total_neurons: int = Field(ge=0)
    active_miners: int = Field(ge=0)
    active_validators: int = Field(ge=0)
    blocks_since_last_step: int = Field(
        default=0, ge=0,
        description="Subnet-level: blocks since last weight-setting step (scalar from SDK)"
    )

    @model_validator(mode="after")
    def validate_neuron_count(self) -> "MetagraphData":
        if len(self.neurons) != self.total_neurons:
            raise ValueError(
                f"neurons list length ({len(self.neurons)}) must match "
                f"total_neurons ({self.total_neurons})"
            )
        return self


class MetagraphSnapshot(BaseModel):
    """Complete metagraph snapshot for a single subnet."""

    metadata: SnapshotMetadata
    data: MetagraphData


# =============================================================================
# Registration Cost Record
# =============================================================================


class RegistrationCost(BaseModel):
    """Registration cost for a single subnet."""

    netuid: int = Field(ge=0)
    registration_cost_tao: float = Field(ge=0.0, description="Cost in TAO")
    block_number: int = Field(ge=0)


class RegistrationCostData(BaseModel):
    """Data payload for registration costs."""

    costs: list[RegistrationCost]


class RegistrationCostRecord(BaseModel):
    """Registration cost record for all monitored subnets."""

    metadata: SnapshotMetadata
    data: RegistrationCostData


# =============================================================================
# Hyperparameter Record
# =============================================================================


class HyperparameterData(BaseModel):
    """On-chain hyperparameters for a subnet.
    
    Field names match Bittensor SDK v10.3.2 get_subnet_hyperparameters() response.
    Note: burn_half_life and burn_increase_mult are NOT exposed by the SDK.
    Registration cost dynamics must be tracked empirically over time.
    """

    immunity_period: int = Field(ge=0, description="Blocks of immunity after registration")
    tempo: int = Field(ge=0, description="Blocks between weight-setting rounds")
    max_validators: int = Field(ge=0, description="Maximum validator slots (SDK field name)")
    min_allowed_weights: int = Field(ge=0)
    activity_cutoff: int = Field(ge=0, description="Blocks before considered inactive")
    max_weight_limit: int = Field(ge=0)
    min_burn: float = Field(ge=0.0, description="Minimum burn in RAO (divide by 1e9 for TAO)")
    max_burn: float = Field(ge=0.0, description="Maximum burn in RAO (divide by 1e9 for TAO)")
    registration_allowed: bool = Field(default=True)
    commit_reveal_weights_enabled: bool = Field(default=False)
    liquid_alpha_enabled: bool = Field(default=False)
    bonds_moving_avg: int = Field(default=900000)
    max_regs_per_block: int = Field(default=1)
    target_regs_per_interval: int = Field(default=2)
    adjustment_interval: int = Field(default=112)
    weights_rate_limit: int = Field(default=100)
    yuma_version: int = Field(default=2, description="Yuma Consensus version (2=YC2)")

    @property
    def min_burn_tao(self) -> float:
        """Min burn converted to TAO."""
        return self.min_burn / 1e9

    @property
    def max_burn_tao(self) -> float:
        """Max burn converted to TAO."""
        return self.max_burn / 1e9

    @property
    def max_miners(self) -> int:
        """Derived: total UID slots (256) minus max_validators."""
        return 256 - self.max_validators


class HyperparameterRecord(BaseModel):
    """Hyperparameter record for a single subnet."""

    metadata: SnapshotMetadata
    data: HyperparameterData


# =============================================================================
# Alpha Price Record
# =============================================================================


class AlphaPrice(BaseModel):
    """Alpha token price and liquidity for a single subnet."""

    netuid: int = Field(ge=0)
    alpha_tao_price: float = Field(ge=0.0, description="Alpha/TAO exchange rate")
    pool_tao_liquidity: float = Field(ge=0.0, description="TAO in AMM pool")
    pool_alpha_liquidity: float = Field(ge=0.0, description="Alpha tokens in AMM pool")


class AlphaPriceData(BaseModel):
    """Data payload for alpha prices."""

    prices: list[AlphaPrice]


class AlphaPriceRecord(BaseModel):
    """Alpha price record for all monitored subnets."""

    metadata: SnapshotMetadata
    data: AlphaPriceData


# =============================================================================
# TAO Price Record
# =============================================================================


class TaoPriceData(BaseModel):
    """TAO/USD price data."""

    tao_usd_price: float = Field(ge=0.0, description="TAO price in USD")
    source: str = Field(description="Price source (e.g., 'coingecko', 'binance')")
    volume_24h_usd: Optional[float] = Field(default=None, ge=0.0)
    market_cap_usd: Optional[float] = Field(default=None, ge=0.0)


class TaoPriceRecord(BaseModel):
    """TAO/USD price record."""

    metadata: SnapshotMetadata
    data: TaoPriceData


# =============================================================================
# Derived Metrics
# =============================================================================


class DeregistrationRisk(BaseModel):
    """Deregistration risk assessment for a single miner."""

    uid: int = Field(ge=0, le=4096)
    hotkey: str
    risk_score: float = Field(ge=0.0, le=1.0)
    emission_rank: int = Field(ge=0)
    immune: bool

    @model_validator(mode="after")
    def immune_miners_have_zero_risk(self) -> "DeregistrationRisk":
        """Immune miners must always have risk_score 0.0."""
        if self.immune and self.risk_score != 0.0:
            raise ValueError("Immune miners must have risk_score 0.0")
        return self


class EmissionTrend(BaseModel):
    """Day-over-day emission change for a subnet."""

    current_total_emission: float = Field(ge=0.0, description="Current total emission in TAO")
    previous_total_emission: float = Field(ge=0.0, description="Previous day total emission in TAO")
    change_percent: float = Field(description="Percentage change as decimal")
    direction: str = Field(description="'increasing', 'declining', or 'stable'")
    seven_day_trend: Optional[float] = Field(
        default=None, description="7-day cumulative change as decimal"
    )

    @field_validator("direction")
    @classmethod
    def validate_direction(cls, v: str) -> str:
        allowed = {"increasing", "declining", "stable"}
        if v not in allowed:
            raise ValueError(f"direction must be one of {allowed}")
        return v


class ROIEstimate(BaseModel):
    """ROI estimation for mining a subnet."""

    net_tao_yield_per_day: float = Field(ge=0.0, description="Net TAO yield per day")
    days_to_recoup: float = Field(ge=0.0, description="Days to recoup registration cost")
    thirty_day_projected_tao: float = Field(description="30-day net TAO projection")
    alpha_tao_rate: float = Field(default=0.0, ge=0.0, description="Alpha/TAO exchange rate")
    slippage_estimate_percent: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Estimated slippage as decimal"
    )
    hold_vs_swap_recommendation: HoldVsSwap = Field(default=HoldVsSwap.SWAP)
    confidence: Confidence = Field(default=Confidence.LOW)


class RewardDistribution(BaseModel):
    """Reward distribution model classification for a subnet."""

    model: RewardModel
    gini_coefficient: float = Field(ge=0.0, le=1.0)
    top_3_concentration: float = Field(ge=0.0, le=1.0)


# Alias for design document compatibility
RewardDistributionModel = RewardDistribution


class TaoflowHealth(BaseModel):
    """Taoflow health status for a subnet."""

    status: TaoflowStatus
    net_staking_flow_tao: float = Field(description="Net staking flow in TAO")
    consecutive_negative_days: int = Field(ge=0)


class ChurnMetrics(BaseModel):
    """Miner churn and competition dynamics for a subnet."""

    daily_churn_rate: float = Field(ge=0.0, le=1.0)
    new_registrations: int = Field(ge=0)
    deregistrations: int = Field(ge=0)
    average_miner_lifespan_blocks: float = Field(ge=0.0)
    competition_trend: CompetitionTrend


class ValidatorLandscape(BaseModel):
    """Validator landscape analysis for a subnet."""

    active_validators: int = Field(ge=0)
    total_validator_stake: float = Field(ge=0.0, description="Total stake in TAO")
    top_1_stake_share: float = Field(ge=0.0, le=1.0)
    top_3_stake_share: float = Field(ge=0.0, le=1.0)
    concentrated: bool = Field(description="True if top-1 validator holds >50% stake")
    avg_validator_activity_blocks: float = Field(ge=0.0)
    net_tao_yield_per_validator_per_day: float = Field(ge=0.0)
    avg_vtrust: float = Field(default=0.0, ge=0.0, le=1.0, description="Average VTrust across validators")
    min_vtrust: float = Field(default=0.0, ge=0.0, le=1.0, description="Minimum VTrust (weakest validator)")


class RentalProfitability(BaseModel):
    """Rental profitability analysis for mining a subnet."""

    cheapest_viable_config: Optional[str] = None
    recommended_provider: Optional[str] = None
    daily_rental_cost_usd: float = Field(default=0.0, ge=0.0)
    daily_tao_yield_usd: float = Field(default=0.0, ge=0.0)
    daily_profit_usd: float = Field(default=0.0)
    monthly_rental_cost_usd: float = Field(default=0.0, ge=0.0)
    monthly_tao_yield: float = Field(default=0.0, ge=0.0)
    rent_vs_buy_multiplier: float = Field(default=0.0, ge=0.0)
    rental_profitable: bool = Field(default=False)
    break_even_tao_price_usd: float = Field(default=0.0, ge=0.0)


class EntryBarrier(BaseModel):
    """Entry barrier assessment for a subnet."""

    score: EntryBarrierLevel
    registration_cost_tao: float = Field(ge=0.0, description="Registration cost in TAO")
    registration_cost_usd: float = Field(ge=0.0, description="Registration cost in USD")
    hardware_tier: HardwareTier
    estimated_monthly_hardware_cost_usd: float = Field(ge=0.0)


class DerivedMetricsData(BaseModel):
    """All derived metrics for a single subnet."""

    deregistration_risk: list[DeregistrationRisk]
    competitive_density: float = Field(ge=0.0, le=1.0)
    emission_trend: EmissionTrend
    roi_estimate: ROIEstimate
    reward_distribution: RewardDistribution
    taoflow_health: TaoflowHealth
    churn: ChurnMetrics
    validator_landscape: ValidatorLandscape
    rental_profitability: RentalProfitability
    entry_barrier: EntryBarrier


class DerivedMetrics(BaseModel):
    """Complete derived metrics record for a subnet."""

    metadata: DerivedMetadata
    data: DerivedMetricsData


# =============================================================================
# Subnet Ranking
# =============================================================================


class SubnetRanking(BaseModel):
    """Ranking entry for a single subnet."""

    netuid: int = Field(ge=0)
    subnet_name: Optional[str] = None
    net_tao_yield: float = Field(ge=0.0, description="Net TAO yield per day")
    days_to_recoup: float = Field(ge=0.0)
    thirty_day_projection: float = Field(description="30-day net TAO projection")
    active_miners: int = Field(ge=0)
    registration_cost: float = Field(ge=0.0, description="Registration cost in TAO")
    competitive_density: float = Field(ge=0.0, le=1.0)
    emission_trend: float = Field(description="Emission change as decimal")
    alpha_price: float = Field(ge=0.0, description="Alpha/TAO price")
    alpha_liquidity: float = Field(ge=0.0, description="Pool TAO liquidity")
    attractiveness_score: float = Field(description="Composite attractiveness score")
    mining_style: Optional[MiningStyle] = None
    hardware_tier: Optional[HardwareTier] = None
    taoflow_status: Optional[TaoflowStatus] = None
    entry_barrier: Optional[EntryBarrierLevel] = None


# =============================================================================
# Daily Briefing
# =============================================================================


class BriefingAlert(BaseModel):
    """A single alert item in the daily briefing."""

    netuid: int = Field(ge=0)
    subnet_name: Optional[str] = None
    alert_type: str = Field(description="Type of alert (e.g., 'emission_change', 'new_subnet')")
    severity: str = Field(description="'info', 'warning', or 'critical'")
    message: str
    metric_value: Optional[float] = None
    previous_value: Optional[float] = None

    @field_validator("severity")
    @classmethod
    def validate_severity(cls, v: str) -> str:
        allowed = {"info", "warning", "critical"}
        if v not in allowed:
            raise ValueError(f"severity must be one of {allowed}")
        return v


class DailyBriefing(BaseModel):
    """Daily briefing summarizing overnight changes."""

    date: str = Field(description="ISO date string YYYY-MM-DD")
    cycle_id: str
    generated_at: datetime
    summary: str = Field(description="Human-readable summary paragraph")
    alerts: list[BriefingAlert]
    new_subnets: list[int] = Field(default_factory=list, description="Newly discovered netuids")
    removed_subnets: list[int] = Field(
        default_factory=list, description="Subnets no longer active"
    )
    top_movers: list[int] = Field(
        default_factory=list, description="Netuids with largest rank changes"
    )
    subnets_processed: int = Field(ge=0)
    subnets_failed: int = Field(ge=0)


# =============================================================================
# Subnet Profile
# =============================================================================


class SubnetProfile(BaseModel):
    """Subnet profile with classification and metadata (convenience aggregate)."""

    netuid: int = Field(ge=0)
    name: str
    description: Optional[str] = None
    category: SubnetCategory = Field(default=SubnetCategory.OTHER)
    mining_style: Optional[MiningStyle] = None
    reward_model: RewardModel = Field(default=RewardModel.UNKNOWN)
    hardware_tier: HardwareTier = Field(default=HardwareTier.CPU_ONLY)
    repo_url: Optional[str] = None
    owner_coldkey: Optional[str] = None
    first_seen_date: Optional[str] = None
    last_updated: Optional[datetime] = None
    notes: Optional[str] = None


# =============================================================================
# Split Subnet Profile Models (DynamoDB 400KB limit compliance)
# =============================================================================


class SubnetProfileBasic(BaseModel):
    """Basic subnet profile stored at SUBNET#{netuid}|PROFILE#basic.

    Contains classification and static metadata that rarely changes.
    """

    netuid: int = Field(ge=0)
    name: str
    description: Optional[str] = None
    category: SubnetCategory = Field(default=SubnetCategory.OTHER)
    mining_style: Optional[MiningStyle] = None
    reward_model: RewardModel = Field(default=RewardModel.UNKNOWN)
    hardware_tier: HardwareTier = Field(default=HardwareTier.CPU_ONLY)
    repo_url: Optional[str] = None
    owner_coldkey: Optional[str] = None
    first_seen_date: Optional[str] = None
    last_updated: Optional[datetime] = None


class WinnerCharacteristics(BaseModel):
    """Characteristics of a top-performing miner."""

    hotkey: str
    uid: int = Field(ge=0, le=4096)
    emission_share: float = Field(ge=0.0, le=1.0)
    stake: float = Field(ge=0.0, description="Stake in TAO")
    blocks_registered: int = Field(ge=0)
    incentive: float = Field(ge=0.0, le=1.0)


class SubnetProfileWinner(BaseModel):
    """Winner profile stored at SUBNET#{netuid}|PROFILE#winner.

    Contains analysis of top-performing miners and their characteristics.
    """

    netuid: int = Field(ge=0)
    top_miners: list[WinnerCharacteristics] = Field(
        default_factory=list, description="Top-5 miners by emission"
    )
    dominant_strategy: Optional[str] = Field(
        default=None, description="Observed winning strategy pattern"
    )
    avg_winner_lifespan_blocks: float = Field(default=0.0, ge=0.0)
    winner_turnover_rate: float = Field(
        default=0.0, ge=0.0, le=1.0, description="Rate of top-5 changes per cycle"
    )
    last_updated: Optional[datetime] = None


class SubnetProfileValidator(BaseModel):
    """Validator profile stored at SUBNET#{netuid}|PROFILE#validator.

    Contains validator landscape analysis and yield data.
    """

    netuid: int = Field(ge=0)
    active_validators: int = Field(default=0, ge=0)
    total_validator_stake: float = Field(default=0.0, ge=0.0, description="Total stake in TAO")
    top_1_stake_share: float = Field(default=0.0, ge=0.0, le=1.0)
    top_3_stake_share: float = Field(default=0.0, ge=0.0, le=1.0)
    concentrated: bool = Field(default=False)
    avg_validator_yield_per_day: float = Field(default=0.0, ge=0.0)
    min_effective_stake: float = Field(
        default=0.0, ge=0.0, description="Minimum stake to earn dividends"
    )
    slots_available: int = Field(default=0, ge=0)
    last_updated: Optional[datetime] = None


class SubnetProfileIntelligence(BaseModel):
    """Intelligence notes stored at SUBNET#{netuid}|PROFILE#intelligence.

    Contains accumulated observations, anomalies, and strategy insights.
    """

    netuid: int = Field(ge=0)
    anomalies: list[str] = Field(default_factory=list, description="Detected anomalies")
    strategy_observations: list[str] = Field(
        default_factory=list, description="Observed mining strategy patterns"
    )
    correlations: list[str] = Field(
        default_factory=list, description="Cross-metric correlations noted"
    )
    risk_factors: list[str] = Field(
        default_factory=list, description="Identified risk factors"
    )
    opportunity_notes: list[str] = Field(
        default_factory=list, description="Identified opportunities"
    )
    last_updated: Optional[datetime] = None


class SubnetProfileComposability(BaseModel):
    """Composability notes stored at SUBNET#{netuid}|PROFILE#composability.

    Contains cross-subnet dependency mapping and service relationships.
    """

    netuid: int = Field(ge=0)
    dependencies: list[int] = Field(
        default_factory=list, description="Netuids this subnet depends on"
    )
    dependents: list[int] = Field(
        default_factory=list, description="Netuids that depend on this subnet"
    )
    service_type: Optional[str] = Field(
        default=None, description="Service role (e.g., 'provider', 'consumer', 'both')"
    )
    cross_subnet_map: dict[str, list[int]] = Field(
        default_factory=dict, description="Mapping of service types to related netuids"
    )
    composability_score: float = Field(
        default=0.0, ge=0.0, le=1.0, description="How composable/interconnected this subnet is"
    )
    last_updated: Optional[datetime] = None


# =============================================================================
# Hotkey Tracking
# =============================================================================


class HotkeyEarnings(BaseModel):
    """Earnings record for a tracked hotkey over a time period."""

    hotkey: str
    period: str = Field(description="Time period: '7d', '30d', or 'all'")
    cumulative_tao: float = Field(ge=0.0, description="Total TAO earned in period")
    subnets: list[int] = Field(default_factory=list, description="Subnets mined in period")
    per_subnet_breakdown: dict[str, float] = Field(
        default_factory=dict,
        description="Mapping of netuid (as string) to TAO earned",
    )
    last_updated: Optional[datetime] = None


class HotkeySnapshot(BaseModel):
    """Daily snapshot of a hotkey's position across subnets."""

    hotkey: str
    date: str = Field(description="ISO date string YYYY-MM-DD")
    positions: list["HotkeyPosition"] = Field(default_factory=list)


class HotkeyPosition(BaseModel):
    """A hotkey's position in a single subnet on a given day."""

    netuid: int = Field(ge=0)
    uid: int = Field(ge=0, le=4096)
    emission: float = Field(ge=0.0, description="Daily emission in TAO")
    incentive: float = Field(ge=0.0, le=1.0)
    rank: int = Field(ge=0, description="Emission rank within subnet")


class HotkeyTracking(BaseModel):
    """Complete tracking record for a watched hotkey.

    Combines earnings summaries with current positions.
    """

    hotkey: str
    label: Optional[str] = Field(default=None, description="Human-readable label for the hotkey")
    earnings_7d: Optional[HotkeyEarnings] = None
    earnings_30d: Optional[HotkeyEarnings] = None
    earnings_all: Optional[HotkeyEarnings] = None
    current_subnets: list[int] = Field(
        default_factory=list, description="Subnets currently registered in"
    )
    registered: bool = Field(default=True, description="Whether hotkey is currently registered")
    first_tracked_date: Optional[str] = None
    last_seen_date: Optional[str] = None


# =============================================================================
# Pipeline Result Models
# =============================================================================


class CollectionResult(BaseModel):
    """Result of the Collector Lambda execution."""

    cycle_id: str = Field(description="ISO date string identifying the pipeline cycle")
    subnets_collected: int = Field(ge=0)
    subnets_failed: int = Field(ge=0)
    collection_timestamp: datetime
    duration_seconds: float = Field(ge=0.0)
    errors: list[str] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        """Collection is successful if at least some subnets were collected."""
        return self.subnets_collected > 0


class ProcessingResult(BaseModel):
    """Result of the Processor Lambda execution for a single subnet."""

    cycle_id: str = Field(description="ISO date string identifying the pipeline cycle")
    netuid: int = Field(ge=0)
    processing_timestamp: datetime
    duration_seconds: float = Field(ge=0.0)
    metrics_computed: list[str] = Field(
        default_factory=list, description="Names of metrics successfully computed"
    )
    errors: list[str] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        """Processing is successful if no errors occurred."""
        return len(self.errors) == 0


class FinalizationResult(BaseModel):
    """Result of the Finalizer Lambda execution."""

    cycle_id: str = Field(description="ISO date string identifying the pipeline cycle")
    finalization_timestamp: datetime
    duration_seconds: float = Field(ge=0.0)
    briefing_generated: bool = Field(default=False)
    rankings_generated: bool = Field(default=False)
    site_generated: bool = Field(default=False)
    subnets_in_cycle: int = Field(ge=0)
    errors: list[str] = Field(default_factory=list)

    @property
    def success(self) -> bool:
        """Finalization is successful if all outputs were generated."""
        return self.briefing_generated and self.rankings_generated and self.site_generated
