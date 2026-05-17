"""Core metrics computation engine for the TAO Mining Intelligence Pipeline.

Implements all algorithms from the design document:
- Algorithm 1: Deregistration Risk
- Algorithm 2: Gini Coefficient
- Algorithm 3: Reward Distribution Model Detection
- Algorithm 4: ROI Estimation
- Algorithm 5: Taoflow Health Detection
- Algorithm 6: Rental Profitability
- Algorithm 7: Miner Churn
- Algorithm 8: Validator Opportunity
- Competitive Density
- Emission Trend
- Validator Landscape
"""

from __future__ import annotations

from typing import Optional

from src.models.enums import (
    CompetitionTrend,
    Confidence,
    HoldVsSwap,
    RewardModel,
    TaoflowStatus,
)
from src.models.schemas import (
    ChurnMetrics,
    DeregistrationRisk,
    EmissionTrend,
    Neuron,
    RentalProfitability,
    RewardDistribution,
    ROIEstimate,
    TaoflowHealth,
    ValidatorLandscape,
)


class MetricsEngine:
    """Core computation engine for all TAO mining intelligence metrics.

    All methods are stateless and operate on provided inputs. This class
    groups the algorithms for organizational clarity and testability.
    """

    # =========================================================================
    # Algorithm 1: Deregistration Risk
    # =========================================================================

    @staticmethod
    def compute_deregistration_risk(
        neurons: list[Neuron],
        current_block: int,
        immunity_period: int,
        recent_registrations_24h: int,
    ) -> list[DeregistrationRisk]:
        """Compute deregistration risk for each miner in a subnet.

        Algorithm 1 from design document.

        Risk score: 0.0 (safe) to 1.0 (imminent deregistration).

        Factors:
        1. Immunity status (immune = 0.0 always)
        2. Subnet occupancy (empty slots = 0.0 for all)
        3. Emission rank position (lower rank = higher risk)
        4. Registration queue pressure (more recent registrations = higher risk)

        Args:
            neurons: All neurons in the subnet metagraph.
            current_block: Current blockchain block number.
            immunity_period: Blocks of immunity after registration (from hyperparams).
            recent_registrations_24h: Number of registrations in the last 24 hours.

        Returns:
            List of DeregistrationRisk for each miner.
        """
        # Identify miners (non-validators or those with incentive)
        miners = [n for n in neurons if n.incentive > 0 or not n.is_validator]

        if not miners:
            return []

        total_slots = len(neurons)
        occupied_slots = sum(1 for n in neurons if n.active)

        # If subnet has empty slots, no one is at risk of deregistration
        if occupied_slots < total_slots:
            return [
                DeregistrationRisk(
                    uid=m.uid,
                    hotkey=m.hotkey,
                    risk_score=0.0,
                    emission_rank=0,
                    immune=True,
                )
                for m in miners
            ]

        # Sort miners by emission ascending (lowest emission = most at risk)
        miners_sorted = sorted(miners, key=lambda m: m.emission)
        num_miners = len(miners_sorted)

        risks: list[DeregistrationRisk] = []
        for rank_idx, miner in enumerate(miners_sorted):
            # Check immunity
            blocks_since_reg = current_block - miner.block_at_registration
            is_immune = blocks_since_reg < immunity_period

            if is_immune:
                risks.append(
                    DeregistrationRisk(
                        uid=miner.uid,
                        hotkey=miner.hotkey,
                        risk_score=0.0,
                        emission_rank=rank_idx,
                        immune=True,
                    )
                )
                continue

            # Queue pressure multiplier: 0 registrations = 0, 10+ = max (1.0)
            queue_pressure = min(recent_registrations_24h / 10.0, 1.0)

            # Only bottom 25% of miners face meaningful risk
            bottom_quartile_size = max(1, int(num_miners * 0.25))

            if rank_idx < bottom_quartile_size:
                # rank_idx 0 = lowest emission = highest risk
                # base_risk: 1.0 for rank 0, decreasing toward 0.0 at quartile boundary
                base_risk = 1.0 - (rank_idx / bottom_quartile_size)
                # Queue pressure amplifies: at 0 pressure, risk is halved
                risk_score = base_risk * (0.5 + 0.5 * queue_pressure)
            else:
                # Top 75% have minimal risk unless queue pressure is extreme
                risk_score = 0.1 * queue_pressure * (1.0 - rank_idx / num_miners)

            risk_score = max(0.0, min(1.0, risk_score))

            risks.append(
                DeregistrationRisk(
                    uid=miner.uid,
                    hotkey=miner.hotkey,
                    risk_score=risk_score,
                    emission_rank=rank_idx,
                    immune=False,
                )
            )

        return risks


    # =========================================================================
    # Algorithm 2: Gini Coefficient
    # =========================================================================

    @staticmethod
    def compute_gini_coefficient(emissions: list[float]) -> float:
        """Compute Gini coefficient of emission distribution.

        Algorithm 2 from design document.

        Uses the O(n log n) sorted-array formula:
            G = (2 * sum((i+1) * x_i)) / (n * sum(x_i)) - (n+1)/n

        Returns:
            0.0 = perfect equality (all miners earn the same)
            1.0 = perfect inequality (one miner earns everything)

        Edge cases:
            - Empty list -> 0.0
            - All zeros -> 0.0
            - Single value -> 0.0
        """
        if not emissions or all(e == 0 for e in emissions):
            return 0.0

        # Filter to positive emissions only (active miners)
        values = sorted([e for e in emissions if e > 0])
        n = len(values)

        if n <= 1:
            return 0.0

        # O(n log n) Gini using sorted array
        cumulative_sum = sum(values)
        weighted_sum = sum((i + 1) * v for i, v in enumerate(values))

        gini = (2.0 * weighted_sum) / (n * cumulative_sum) - (n + 1.0) / n
        return max(0.0, min(1.0, gini))

    # =========================================================================
    # Algorithm 3: Reward Distribution Model Detection
    # =========================================================================

    @staticmethod
    def _has_tiered_pattern(sorted_emissions: list[float]) -> bool:
        """Detect step-function pattern in emission distribution.

        Looks for significant gaps (>50% drop) between adjacent miners
        in the sorted emission list. A tiered pattern has 1-3 such gaps,
        indicating 2-4 distinct reward tiers.

        Args:
            sorted_emissions: Emissions sorted in descending order.

        Returns:
            True if a tiered pattern is detected.
        """
        if len(sorted_emissions) < 6:
            return False

        significant_gaps = 0
        for i in range(1, len(sorted_emissions)):
            if sorted_emissions[i - 1] > 0:
                ratio = sorted_emissions[i] / sorted_emissions[i - 1]
                if ratio < 0.5:  # More than 50% drop
                    significant_gaps += 1

        # Tiered = 2-4 distinct tiers (1-3 significant gaps)
        return 1 <= significant_gaps <= 3

    @staticmethod
    def detect_reward_distribution_model(
        emissions: list[float],
    ) -> tuple[RewardModel, float, float]:
        """Classify subnet reward distribution model.

        Algorithm 3 from design document.

        Classification rules:
        - WINNER_TAKES_ALL: top 3 miners > 70% of total emission
        - PROPORTIONAL: Gini < 0.5
        - TIERED: distinct emission clusters (step-function pattern)
        - UNKNOWN: doesn't fit above categories

        Args:
            emissions: List of emission values for all neurons.

        Returns:
            Tuple of (RewardModel enum, gini_coefficient, top_3_concentration).
        """
        active_emissions = [e for e in emissions if e > 0]

        if len(active_emissions) < 3:
            return (RewardModel.UNKNOWN, 0.0, 1.0)

        total = sum(active_emissions)
        sorted_desc = sorted(active_emissions, reverse=True)

        top_3_share = sum(sorted_desc[:3]) / total if total > 0 else 0.0
        gini = MetricsEngine.compute_gini_coefficient(active_emissions)

        # Check WTA first (most restrictive)
        if top_3_share > 0.70:
            return (RewardModel.WINNER_TAKES_ALL, gini, top_3_share)

        # Check proportional
        if gini < 0.5:
            return (RewardModel.PROPORTIONAL, gini, top_3_share)

        # Check for tiered pattern
        if MetricsEngine._has_tiered_pattern(sorted_desc):
            return (RewardModel.TIERED, gini, top_3_share)

        return (RewardModel.UNKNOWN, gini, top_3_share)


    # =========================================================================
    # Algorithm 4: ROI Estimation
    # =========================================================================

    @staticmethod
    def _estimate_slippage(
        sell_amount_alpha: float, alpha_price: float, pool_tao: float
    ) -> float:
        """Estimate slippage for selling alpha tokens using constant product AMM.

        For constant product AMM: x * y = k
        Slippage = 1 - (actual_output / expected_output)

        NOTE: This provides a CONSERVATIVE UPPER BOUND on slippage. Bittensor's
        base subnet pool uses constant product (x*y=k), but the network also
        supports Uniswap V3-style concentrated liquidity positions that add depth
        at specific price ranges. Actual slippage may be lower than this estimate
        when concentrated liquidity is active near the current price. For risk
        assessment purposes, the upper bound is preferred (we'd rather overestimate
        slippage than underestimate).

        Args:
            sell_amount_alpha: Amount of alpha tokens to sell.
            alpha_price: Current alpha/TAO exchange rate.
            pool_tao: TAO liquidity in the AMM pool.

        Returns:
            Slippage as a decimal in [0.0, 1.0]. 1.0 means cannot sell.
        """
        if pool_tao <= 0 or alpha_price <= 0:
            return 1.0  # 100% slippage = can't sell

        if sell_amount_alpha <= 0:
            return 0.0

        # Derive pool alpha from price: price = tao/alpha -> alpha = tao/price
        pool_alpha = pool_tao / alpha_price
        k = pool_tao * pool_alpha

        # After selling `sell_amount_alpha` into pool:
        new_pool_alpha = pool_alpha + sell_amount_alpha
        new_pool_tao = k / new_pool_alpha
        actual_tao_received = pool_tao - new_pool_tao

        expected_tao = sell_amount_alpha * alpha_price

        if expected_tao <= 0:
            return 0.0

        slippage = 1.0 - (actual_tao_received / expected_tao)
        # Floor at 0: floating point noise can produce tiny negative values
        # or non-monotonic results at extremely small sell/pool ratios
        slippage = max(0.0, min(1.0, slippage))
        # Treat sub-microscoptic slippage as zero (floating point noise)
        if slippage < 1e-7:
            slippage = 0.0
        return slippage

    @staticmethod
    def compute_roi_estimates(
        neurons: list[Neuron],
        registration_cost_tao: float,
        alpha_tao_price: float,
        pool_tao_liquidity: float,
        historical_alpha_prices: Optional[list[float]] = None,
    ) -> ROIEstimate:
        """Compute net TAO yield and payback timeline for mining a subnet.

        Algorithm 4 from design document.

        Core formula:
        - net_tao_yield_per_day = avg_daily_alpha_emission_per_miner x alpha_tao_price
        - days_to_recoup = registration_cost_tao / net_tao_yield_per_day
        - thirty_day_projection = (net_tao_yield_per_day x 30) - registration_cost_tao

        Args:
            neurons: All neurons in the subnet.
            registration_cost_tao: Cost to register in TAO.
            alpha_tao_price: Current alpha/TAO exchange rate.
            pool_tao_liquidity: TAO in the AMM pool.
            historical_alpha_prices: Optional 7-day price history for trend analysis.

        Returns:
            ROIEstimate with yield, payback, and projection data.
        """
        miner_emissions = [
            n.emission for n in neurons if n.active and n.incentive > 0
        ]

        if not miner_emissions or alpha_tao_price <= 0:
            return ROIEstimate(
                net_tao_yield_per_day=0.0,
                days_to_recoup=float("inf"),
                thirty_day_projected_tao=-registration_cost_tao,
                alpha_tao_rate=max(0.0, alpha_tao_price),
                slippage_estimate_percent=0.0,
                hold_vs_swap_recommendation=HoldVsSwap.SWAP,
                confidence=Confidence.LOW,
            )

        # Average daily alpha emission per miner
        avg_alpha_emission = sum(miner_emissions) / len(miner_emissions)

        # Convert to TAO equivalent
        net_tao_yield_per_day = avg_alpha_emission * alpha_tao_price

        # Days to recoup registration cost
        days_to_recoup = (
            registration_cost_tao / net_tao_yield_per_day
            if net_tao_yield_per_day > 0
            else float("inf")
        )

        # 30-day projection (net of registration cost)
        thirty_day_tao = (net_tao_yield_per_day * 30) - registration_cost_tao

        # Slippage estimate based on liquidity
        slippage = MetricsEngine._estimate_slippage(
            avg_alpha_emission, alpha_tao_price, pool_tao_liquidity
        )

        # Hold vs swap recommendation based on alpha price trend
        hold_vs_swap = HoldVsSwap.SWAP  # default: convert to TAO immediately
        if historical_alpha_prices and len(historical_alpha_prices) >= 7:
            first_price = historical_alpha_prices[0]
            if first_price > 0:
                price_trend = (
                    historical_alpha_prices[-1] - first_price
                ) / first_price
                if price_trend > 0.05:  # Alpha appreciating > 5% over 7 days
                    hold_vs_swap = HoldVsSwap.HOLD

        # Confidence based on data availability
        confidence = (
            Confidence.HIGH
            if historical_alpha_prices and len(historical_alpha_prices) >= 7
            else Confidence.LOW
        )

        return ROIEstimate(
            net_tao_yield_per_day=net_tao_yield_per_day,
            days_to_recoup=days_to_recoup,
            thirty_day_projected_tao=thirty_day_tao,
            alpha_tao_rate=alpha_tao_price,
            slippage_estimate_percent=slippage,
            hold_vs_swap_recommendation=hold_vs_swap,
            confidence=confidence,
        )


    # =========================================================================
    # Algorithm 5: Taoflow Health Detection
    # =========================================================================

    @staticmethod
    def compute_taoflow_health(
        stake_history: list[float],
        emission_history: list[float],
    ) -> TaoflowHealth:
        """Detect subnets entering death spiral under Taoflow emission model.

        Algorithm 5 from design document.

        Rules:
        - "healthy": fewer than 3 consecutive negative staking flow days
        - "declining": net staking flow negative for 3-6 consecutive days
        - "death_spiral_risk": negative flow 7+ days AND emission down >25%

        Args:
            stake_history: Daily total stake values, most recent last.
            emission_history: Daily total emission values, most recent last.

        Returns:
            TaoflowHealth with status, net flow, and consecutive negative days.
        """
        if len(stake_history) < 2:
            return TaoflowHealth(
                status=TaoflowStatus.HEALTHY,
                net_staking_flow_tao=0.0,
                consecutive_negative_days=0,
            )

        # Compute daily net staking flows
        daily_flows = [
            stake_history[i] - stake_history[i - 1]
            for i in range(1, len(stake_history))
        ]

        # Count consecutive negative days (from most recent)
        consecutive_negative = 0
        for flow in reversed(daily_flows):
            if flow < 0:
                consecutive_negative += 1
            else:
                break

        # Current net flow (most recent day)
        current_flow = daily_flows[-1] if daily_flows else 0.0

        # Check death spiral: 7+ negative days AND emission decline > 25%
        if consecutive_negative >= 7 and len(emission_history) >= 8:
            emission_7d_ago = emission_history[-8]
            emission_now = emission_history[-1]
            if emission_7d_ago > 0:
                emission_decline = (emission_7d_ago - emission_now) / emission_7d_ago
                if emission_decline > 0.25:
                    return TaoflowHealth(
                        status=TaoflowStatus.DEATH_SPIRAL_RISK,
                        net_staking_flow_tao=current_flow,
                        consecutive_negative_days=consecutive_negative,
                    )

        # Check declining: 3+ consecutive negative days
        if consecutive_negative >= 3:
            return TaoflowHealth(
                status=TaoflowStatus.DECLINING,
                net_staking_flow_tao=current_flow,
                consecutive_negative_days=consecutive_negative,
            )

        return TaoflowHealth(
            status=TaoflowStatus.HEALTHY,
            net_staking_flow_tao=current_flow,
            consecutive_negative_days=consecutive_negative,
        )

    # =========================================================================
    # Algorithm 6: Rental Profitability
    # =========================================================================

    @staticmethod
    def compute_rental_profitability(
        net_tao_yield_per_day: float,
        tao_usd_price: float,
        hardware_tier: str,
        cloud_pricing: dict[str, dict[str, float]],
    ) -> RentalProfitability:
        """Determine if renting cloud GPUs to mine is profitable.

        Algorithm 6 from design document.

        Core metrics:
        - daily_profit_usd = (net_tao_yield x tao_usd) - daily_rental_cost
        - rent_vs_buy_multiplier = tao_earned_by_mining / tao_buyable_with_rental_cost
        - break_even_tao_price = daily_rental_cost / net_tao_yield_per_day

        Args:
            net_tao_yield_per_day: Expected daily TAO yield from mining.
            tao_usd_price: Current TAO/USD price.
            hardware_tier: Hardware tier string (e.g., "CONSUMER_GPU").
            cloud_pricing: Nested dict {provider: {gpu_config: hourly_rate_usd}}.

        Returns:
            RentalProfitability with cost analysis and recommendation.
        """
        # Map hardware tier to viable GPU configs
        tier_to_configs: dict[str, list[str]] = {
            "CPU_ONLY": [],
            "CONSUMER_GPU": ["RTX 4090", "RTX 3090"],
            "DATACENTER_GPU": ["A100 40GB", "A100 80GB"],
            "MULTI_GPU": ["2xA100", "4xA100"],
            "SPECIALIZED": ["H100", "8xH100"],
        }

        viable_configs = tier_to_configs.get(hardware_tier, [])
        if not viable_configs:
            # CPU-only or unknown tier: no GPU rental needed
            return RentalProfitability(rental_profitable=False)

        # Find cheapest viable option across all providers
        best_option: Optional[tuple[str, str, float]] = None
        best_daily_cost = float("inf")

        for provider, configs in cloud_pricing.items():
            for config_name, hourly_rate in configs.items():
                if config_name in viable_configs:
                    daily_cost = hourly_rate * 24
                    if daily_cost < best_daily_cost:
                        best_daily_cost = daily_cost
                        best_option = (provider, config_name, daily_cost)

        if best_option is None:
            # No pricing data for viable configs
            return RentalProfitability(rental_profitable=False)

        provider, config, daily_cost = best_option

        # Daily profit/loss
        daily_tao_value_usd = net_tao_yield_per_day * tao_usd_price
        daily_profit_usd = daily_tao_value_usd - daily_cost

        # Rent-vs-buy multiplier: TAO mined vs TAO buyable with rental cost
        tao_buyable_per_day = (
            daily_cost / tao_usd_price if tao_usd_price > 0 else 0.0
        )
        rent_vs_buy = (
            net_tao_yield_per_day / tao_buyable_per_day
            if tao_buyable_per_day > 0
            else 0.0
        )

        # Break-even TAO price: price at which mining revenue equals rental cost
        break_even = (
            daily_cost / net_tao_yield_per_day
            if net_tao_yield_per_day > 0
            else 0.0
        )

        return RentalProfitability(
            cheapest_viable_config=config,
            recommended_provider=provider,
            daily_rental_cost_usd=daily_cost,
            daily_tao_yield_usd=daily_tao_value_usd,
            daily_profit_usd=daily_profit_usd,
            monthly_rental_cost_usd=daily_cost * 30,
            monthly_tao_yield=net_tao_yield_per_day * 30,
            rent_vs_buy_multiplier=rent_vs_buy,
            rental_profitable=rent_vs_buy > 1.0,
            break_even_tao_price_usd=break_even,
        )


    # =========================================================================
    # Algorithm 7: Miner Churn
    # =========================================================================

    @staticmethod
    def compute_miner_churn(
        current_hotkeys: set[str],
        previous_hotkeys: set[str],
        current_registrations: list[dict],
        current_block: int,
    ) -> ChurnMetrics:
        """Compute daily churn rate and competition dynamics.

        Algorithm 7 from design document.

        churn_rate = (new_registrations + deregistrations) / total_miners
        avg_lifespan = mean(current_block - block_at_registration) for active miners
        trend: INCREASING if net change > +5%, DECREASING if < -5%, else STABLE

        Args:
            current_hotkeys: Set of hotkeys currently registered.
            previous_hotkeys: Set of hotkeys from previous snapshot.
            current_registrations: List of dicts with 'block_at_registration' and 'active'.
            current_block: Current blockchain block number.

        Returns:
            ChurnMetrics with churn rate, registrations, and trend.
        """
        new_miners = current_hotkeys - previous_hotkeys
        departed_miners = previous_hotkeys - current_hotkeys
        total_miners = len(current_hotkeys)

        churn_rate = (
            (len(new_miners) + len(departed_miners)) / total_miners
            if total_miners > 0
            else 0.0
        )
        # Clamp to [0, 1]
        churn_rate = max(0.0, min(1.0, churn_rate))

        # Average miner lifespan in blocks
        lifespans = [
            current_block - reg["block_at_registration"]
            for reg in current_registrations
            if reg.get("active")
        ]
        avg_lifespan = sum(lifespans) / len(lifespans) if lifespans else 0.0

        # Competition trend based on net change percentage
        net_change = len(new_miners) - len(departed_miners)
        net_change_pct = net_change / total_miners if total_miners > 0 else 0.0

        if net_change_pct > 0.05:
            trend = CompetitionTrend.INCREASING
        elif net_change_pct < -0.05:
            trend = CompetitionTrend.DECREASING
        else:
            trend = CompetitionTrend.STABLE

        return ChurnMetrics(
            daily_churn_rate=churn_rate,
            new_registrations=len(new_miners),
            deregistrations=len(departed_miners),
            average_miner_lifespan_blocks=avg_lifespan,
            competition_trend=trend,
        )

    # =========================================================================
    # Validator Landscape
    # =========================================================================

    @staticmethod
    def compute_validator_landscape(
        neurons: list[Neuron],
        alpha_tao_price: float,
    ) -> ValidatorLandscape:
        """Compute validator landscape analysis for a subnet.

        Analyzes validator count, stake concentration, activity, and yield.

        Args:
            neurons: All neurons in the subnet.
            alpha_tao_price: Current alpha/TAO exchange rate.

        Returns:
            ValidatorLandscape with concentration and yield metrics.
        """
        validators = [n for n in neurons if n.dividends > 0]

        if not validators:
            return ValidatorLandscape(
                active_validators=0,
                total_validator_stake=0.0,
                top_1_stake_share=0.0,
                top_3_stake_share=0.0,
                concentrated=False,
                avg_validator_activity_blocks=0.0,
                net_tao_yield_per_validator_per_day=0.0,
            )

        total_stake = sum(v.stake for v in validators)
        validators_by_stake = sorted(validators, key=lambda v: v.stake, reverse=True)

        # Top-1 and top-3 stake shares
        top_1_share = (
            validators_by_stake[0].stake / total_stake if total_stake > 0 else 0.0
        )
        top_3_stakes = sum(v.stake for v in validators_by_stake[:3])
        top_3_share = top_3_stakes / total_stake if total_stake > 0 else 0.0

        # Average validator activity (blocks since last step is subnet-level, not per-neuron)
        # Use a default value since this metric requires subnet-level data passed separately
        avg_activity = 0.0  # Will be populated from subnet-level blocks_since_last_step

        # Net TAO yield per validator per day
        avg_dividends = sum(v.dividends for v in validators) / len(validators)
        # dividends is normalized [0,1], emission is in TAO
        avg_emission = sum(v.emission for v in validators) / len(validators)
        net_yield = avg_emission * alpha_tao_price

        return ValidatorLandscape(
            active_validators=len(validators),
            total_validator_stake=total_stake,
            top_1_stake_share=min(1.0, top_1_share),
            top_3_stake_share=min(1.0, top_3_share),
            concentrated=top_1_share > 0.5,
            avg_validator_activity_blocks=avg_activity,
            net_tao_yield_per_validator_per_day=net_yield,
        )


    # =========================================================================
    # Algorithm 8: Validator Opportunity Assessment
    # =========================================================================

    @staticmethod
    def compute_validator_opportunity(
        neurons: list[Neuron],
        alpha_tao_price: float,
        max_allowed_validators: int,
    ) -> dict:
        """Assess validation as a TAO accumulation strategy.

        Algorithm 8 from design document.

        Key metrics:
        - net_tao_yield_per_validator = avg_dividends x alpha_tao_price
        - minimum_effective_stake = stake of bottom 10% earning validator
        - validator_roi = daily_yield / stake_committed
        - slot_availability = max_validators - current_validators

        Args:
            neurons: All neurons in the subnet.
            alpha_tao_price: Current alpha/TAO exchange rate.
            max_allowed_validators: Maximum validators allowed by subnet hyperparams.

        Returns:
            Dict with keys: viable, net_tao_yield, min_effective_stake,
            daily_roi_percent, slots_available, concentrated.
        """
        validators = [n for n in neurons if n.dividends > 0]

        if not validators:
            return {
                "viable": False,
                "net_tao_yield": 0.0,
                "min_effective_stake": 0.0,
                "daily_roi_percent": 0.0,
                "slots_available": max_allowed_validators,
                "concentrated": False,
            }

        # Net TAO yield per validator (using emission directly)
        avg_emission = sum(v.emission for v in validators) / len(validators)
        net_tao_yield = avg_emission * alpha_tao_price

        # Minimum effective stake (bottom 10% threshold)
        validators_by_dividends = sorted(validators, key=lambda v: v.dividends)
        bottom_10_idx = max(1, len(validators_by_dividends) // 10)
        # Clamp index to valid range
        bottom_10_idx = min(bottom_10_idx, len(validators_by_dividends) - 1)
        min_effective_stake = validators_by_dividends[bottom_10_idx].stake

        # Validator ROI (daily)
        avg_stake = sum(v.stake for v in validators) / len(validators)
        daily_roi = net_tao_yield / avg_stake if avg_stake > 0 else 0.0

        # Slot availability
        slots_available = max(0, max_allowed_validators - len(validators))

        # Stake concentration
        total_stake = sum(v.stake for v in validators)
        top_1_share = (
            max(v.stake for v in validators) / total_stake
            if total_stake > 0
            else 0.0
        )

        return {
            "viable": True,
            "net_tao_yield": net_tao_yield,
            "min_effective_stake": min_effective_stake,
            "daily_roi_percent": daily_roi * 100,
            "slots_available": slots_available,
            "concentrated": top_1_share > 0.5,
        }

    # =========================================================================
    # Competitive Density (simple ratio)
    # =========================================================================

    @staticmethod
    def compute_competitive_density(neurons: list[Neuron]) -> float:
        """Compute competitive density as active miners / total miner emission.

        A simple measure of how crowded the mining field is. Higher values
        indicate more competition for the same emission pool.

        Args:
            neurons: All neurons in the subnet.

        Returns:
            Float in [0.0, 1.0] representing competitive density.
        """
        miners = [n for n in neurons if n.incentive > 0 or not n.is_validator]

        if not miners:
            return 0.0

        active_miners = sum(1 for m in miners if m.active)
        total_emission = sum(m.emission for m in miners)

        if total_emission <= 0:
            return 0.0

        # Ratio of active miners to total emission, capped at 1.0
        # Normalized: more miners competing for same emission = higher density
        density = active_miners / (active_miners + total_emission)
        return max(0.0, min(1.0, density))

    # =========================================================================
    # Emission Trend (day-over-day)
    # =========================================================================

    @staticmethod
    def compute_emission_trend(
        current_total_emission: float,
        previous_total_emission: float,
        seven_day_emissions: Optional[list[float]] = None,
    ) -> EmissionTrend:
        """Compute day-over-day emission change for a subnet.

        Args:
            current_total_emission: Current day's total emission in TAO.
            previous_total_emission: Previous day's total emission in TAO.
            seven_day_emissions: Optional list of 7 daily emission totals
                (oldest first) for trend calculation.

        Returns:
            EmissionTrend with change percentage and direction.
        """
        # Compute day-over-day change
        if previous_total_emission > 0:
            change_percent = (
                current_total_emission - previous_total_emission
            ) / previous_total_emission
        else:
            change_percent = 0.0

        # Determine direction
        if change_percent > 0.01:  # >1% increase
            direction = "increasing"
        elif change_percent < -0.01:  # >1% decrease
            direction = "declining"
        else:
            direction = "stable"

        # 7-day cumulative trend
        seven_day_trend: Optional[float] = None
        if seven_day_emissions and len(seven_day_emissions) >= 2:
            first = seven_day_emissions[0]
            last = seven_day_emissions[-1]
            if first > 0:
                seven_day_trend = (last - first) / first

        return EmissionTrend(
            current_total_emission=current_total_emission,
            previous_total_emission=previous_total_emission,
            change_percent=change_percent,
            direction=direction,
            seven_day_trend=seven_day_trend,
        )


# =============================================================================
# Standalone functions for property testing (simple types, no Pydantic models)
# =============================================================================


def compute_deregistration_risk(
    emissions: list[float],
    is_immune: list[bool],
    total_slots: int,
    occupied_slots: int,
    recent_registrations_24h: int,
) -> list[float]:
    """Standalone deregistration risk function for property testing.

    Takes simple types (no Pydantic models) for easy Hypothesis generation.
    Returns list of risk scores in the same order as input emissions.

    Args:
        emissions: Emission values per miner.
        is_immune: Whether each miner is within immunity period.
        total_slots: Total UID slots in the subnet.
        occupied_slots: Currently occupied slots.
        recent_registrations_24h: Recent registration activity.

    Returns:
        List of risk scores [0.0, 1.0] in same order as input.
    """
    n = len(emissions)
    if n == 0:
        return []

    # If subnet has empty slots, no one is at risk
    if occupied_slots < total_slots:
        return [0.0] * n

    # Create indexed list for sorting while preserving original order
    indexed = list(enumerate(zip(emissions, is_immune)))
    # Sort by emission ascending (lowest = most at risk)
    sorted_by_emission = sorted(indexed, key=lambda x: x[1][0])

    # Compute risks
    risks = [0.0] * n
    num_miners = len(sorted_by_emission)
    bottom_quartile_size = max(1, int(num_miners * 0.25))
    queue_pressure = min(recent_registrations_24h / 10.0, 1.0)

    for rank_idx, (original_idx, (emission, immune)) in enumerate(sorted_by_emission):
        if immune:
            risks[original_idx] = 0.0
            continue

        if rank_idx < bottom_quartile_size:
            base_risk = 1.0 - (rank_idx / bottom_quartile_size)
            risk_score = base_risk * (0.5 + 0.5 * queue_pressure)
        else:
            risk_score = 0.1 * queue_pressure * (1.0 - rank_idx / num_miners)

        risks[original_idx] = max(0.0, min(1.0, risk_score))

    return risks
