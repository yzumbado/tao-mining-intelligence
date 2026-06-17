"""Core metrics computation engine for the TAO Mining Intelligence Pipeline.

Implements all algorithms from the design document:
- Algorithm 1: Deregistration Risk
- Algorithm 2: Gini Coefficient
- Algorithm 3: Reward Distribution Model Detection
- Algorithm 4: ROI Estimation
- Algorithm 5: Taoflow Health Detection
- Algorithm 7: Miner Churn
- Algorithm 8: Validator Opportunity
- Competitive Density
- Emission Trend
- Validator Landscape

METRICS DOCUMENTATION:
    Each metric method contains a structured `Metric:` block in its docstring.
    The living reference guide (kb/metrics-reference.md) is AUTO-GENERATED from
    these blocks by running:

        python scripts/generate_metrics_reference.py

    When adding or modifying a metric, update the `Metric:` block in the docstring,
    then re-run the generator. Do NOT edit kb/metrics-reference.md manually.

    Metric block format:
        Metric:
            name: Human-readable metric name
            status: PROVEN | HYPOTHESIS | NEEDS_VALIDATION | DEPRECATED
            hypothesis: What this metric represents and why
            usefulness_mining: How it helps mining decisions
            usefulness_staking: How it helps staking decisions
            usefulness_risk: How it helps risk management
            output_range: Valid output values
            known_issues: Any known problems or limitations
            assumptions: Things that need validation
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
        num_uids: Optional[int] = None,
        max_uids: Optional[int] = None,
    ) -> list[DeregistrationRisk]:
        """Compute deregistration risk for each miner in a subnet.

        Algorithm 1 from design document.

        Risk score: 0.0 (safe) to 1.0 (imminent deregistration).

        Factors:
        1. Immunity status (immune = 0.0 always)
        2. Subnet occupancy (empty slots = 0.0 for all)
        3. Emission rank position (lower rank = higher risk)
        4. Registration queue pressure (more recent registrations = higher risk)

        Metric:
            name: Deregistration Risk
            status: HYPOTHESIS
            hypothesis: |
                On a full subnet, the miner with the lowest emission is replaced when
                a new registrant arrives. Queue pressure (recent registrations) indicates
                how actively people are trying to enter. Bottom 25% face real risk;
                top 75% are safe unless registration pressure is extreme.
            formula: |
                IF num_uids < max_uids (subnet not full) → risk = 0.0 for all
                IF miner is immune (blocks_since_reg < immunity_period) → risk = 0.0
                queue_pressure = min(recent_registrations_24h / 10, 1.0)
                IF miner in bottom 25% by emission:
                    base_risk = 1.0 - (rank / bottom_quartile_size)
                    risk = base_risk × (0.5 + 0.5 × queue_pressure)
                ELSE: risk = 0.1 × queue_pressure × (1.0 - rank / total_miners)
            usefulness_mining: Tells you if entering a subnet is risky — high churn means you must be competitive immediately after immunity
            usefulness_staking: Indirectly useful — high deregistration means competitive subnet (good for validators)
            usefulness_risk: Track your own miner's risk score over time; exit before deregistration
            output_range: "[0.0, 1.0] per miner"
            known_issues: |
                - Bottom 25% threshold may not be correct for all subnets
                - Queue pressure cap of 10 registrations/day may be too low for popular subnets
                - pruning_score field exists in SDK docs but returns empty list in v10
            assumptions: |
                - Is the bottom 25% threshold correct?
                - Does queue_pressure of 10/day represent max pressure?
                - Will pruning_score become available in future SDK versions?

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

        # DECISION: DEREG-001
        # Choice: Use num_uids >= max_uids for subnet fullness (not sum(active))
        # Alternatives rejected: sum(active) — active means "set weights recently", not "slot occupied"
        # Rationale: Official Bittensor docs define num_uids/max_uids for this purpose.
        #   Live data shows subnets with 256 registered neurons but only 12 active=True.
        # Revisit when: Bittensor changes deregistration mechanics
        # Evidence: Live chain SN95: num_uids=256, max_uids=256, active.sum()=12
        if num_uids is not None and max_uids is not None:
            subnet_full = num_uids >= max_uids
        else:
            # Backward compat: fall back to counting neurons with non-default hotkeys
            subnet_full = len(neurons) >= 256  # conservative default

        if not subnet_full:
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
                # Above bottom quartile: monotonically decreasing from boundary
                remaining = num_miners - bottom_quartile_size
                position = rank_idx - bottom_quartile_size
                min_bq_risk = (1.0 / bottom_quartile_size) * (0.5 + 0.5 * queue_pressure)
                risk_score = min_bq_risk * (1.0 - (position + 1) / (remaining + 1))

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

        Metric:
            name: Gini Coefficient
            status: PROVEN
            hypothesis: |
                Standard economics measure of inequality. Measures how concentrated
                rewards are among miners. Gini 0.9+ means almost all emission goes to
                a few miners (WTA). Gini 0.3 means rewards are spread relatively evenly.
            formula: |
                Given sorted positive emissions [x₁, x₂, ..., xₙ] (ascending):
                G = (2 × Σᵢ (i+1)×xᵢ) / (n × Σxᵢ) - (n+1)/n
                Edge cases: empty/all-zero → 0.0, single value → 0.0
            usefulness_mining: High Gini = must be top-few or earn nothing. Low Gini = even mediocre miners earn.
            usefulness_staking: High Gini subnets have more predictable top performers (stable for validators)
            usefulness_risk: Primary input to Reward Distribution Model detection
            output_range: "[0.0, 1.0] — 0 = equality, 1 = one miner gets everything"
            known_issues: None — standard formula
            assumptions: None — mathematically proven

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

        Metric:
            name: Reward Distribution Model
            status: HYPOTHESIS
            hypothesis: |
                Subnets fall into distinct reward patterns: WTA (top 3 capture >70%),
                PROPORTIONAL (Gini < 0.5, all earn proportionally), TIERED (distinct
                quality thresholds create step-function in emissions). Classification
                determines what "winning" means on each subnet.
            formula: |
                top_3_share = sum(top 3 emissions) / sum(all emissions)
                gini = compute_gini_coefficient(active_emissions)
                IF top_3_share > 0.70 → WINNER_TAKES_ALL
                ELIF gini < 0.5 → PROPORTIONAL
                ELIF has_tiered_pattern (1-3 gaps with >50% drop) → TIERED
                ELSE → UNKNOWN
            usefulness_mining: Critical — on WTA you must be top-3 or earn nothing; on PROPORTIONAL even mediocre miners earn
            usefulness_staking: WTA subnets have more predictable top performers → stable validator returns
            usefulness_risk: Determines strategy — WTA requires excellence, PROPORTIONAL allows mediocrity
            output_range: "Enum {WINNER_TAKES_ALL, PROPORTIONAL, TIERED, UNKNOWN} + gini + top_3_concentration"
            known_issues: |
                - 70% WTA threshold is an educated guess, not empirically derived
                - Gini < 0.5 for PROPORTIONAL may be too generous
                - Tiered pattern detection is heuristic (gap-based)
            assumptions: |
                - Is 70% the right WTA threshold?
                - Is Gini < 0.5 the right PROPORTIONAL boundary?
                - First live run confirmed 4/247 miners earn on SN1 — validates WTA detection

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

        Metric:
            name: AMM Slippage Estimation
            status: HYPOTHESIS
            hypothesis: |
                When selling alpha for TAO, the AMM pool moves against you. Larger sells
                relative to pool size = more slippage. This is a CONSERVATIVE UPPER BOUND
                because Bittensor also supports concentrated liquidity (Uniswap V3-style).
            formula: |
                pool_alpha = pool_tao / alpha_price
                k = pool_tao × pool_alpha
                new_pool_alpha = pool_alpha + sell_amount
                actual_tao = pool_tao - (k / new_pool_alpha)
                slippage = 1 - (actual_tao / (sell_amount × alpha_price))
            usefulness_mining: "Can I actually realize this yield?" — high slippage means paper yield > real yield
            usefulness_staking: Same — validator dividends in alpha need conversion to TAO
            usefulness_risk: Subnets with thin pools are risky even if yield looks good
            output_range: "[0.0, 1.0] — 0 = no slippage, 1 = cannot sell"
            known_issues: |
                - Conservative upper bound — real slippage may be lower with concentrated liquidity
                - Doesn't account for multiple sells over time (pool recovers between trades)
            assumptions: |
                - Is constant-product the right model for Bittensor's base pool?
                - How much does concentrated liquidity reduce actual slippage?

        For constant product AMM: x * y = k
        Slippage = 1 - (actual_output / expected_output)

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

        Metric:
            name: ROI Estimation (Net TAO Yield)
            status: HYPOTHESIS
            hypothesis: |
                If you register on this subnet and perform at the average earning miner
                level, this is what you'd earn. The alpha→TAO conversion via the AMM pool
                determines your real return. Averages across EARNING miners only (emission > 0)
                to avoid dilution by zero-earners on WTA subnets.
            formula: |
                miner_emissions = [n.emission for n if n.incentive > 0 AND n.dividends == 0]  # pure miners only
                avg_daily_alpha = sum(miner_emissions) / len(miner_emissions)
                net_tao_yield_per_day = avg_daily_alpha × alpha_tao_price
                days_to_recoup = registration_cost_tao / net_tao_yield_per_day
                thirty_day_projection = (net_tao_yield × 30) - registration_cost
            usefulness_mining: Primary decision metric — "is this subnet worth entering?"
            usefulness_staking: The validator variant (Metric 8) is the staking equivalent
            usefulness_risk: days_to_recoup tells you how long your capital is at risk
            output_range: "net_tao_yield: [0, ∞) TAO/day; days_to_recoup: [0, ∞]; thirty_day: (-∞, ∞) TAO"
            known_issues: |
                - Average emission is misleading on WTA subnets (most earn 0, avg pulled up by top)
                - No adjustment for YOUR likely rank position — assumes you'd be average
                - Slippage estimate is conservative upper bound (ignores concentrated liquidity)
            assumptions: |
                - Does averaging across earning miners give a realistic estimate?
                - Should we use median instead of mean for WTA subnets?
                - Is constant-product AMM slippage model accurate for Bittensor pools?
                - Is 5% over 7 days the right hold-vs-swap threshold?
            validated_against: |
                - Live chain metagraph (5 subnets, ±0.6% deviation) — 2026-06-03
                - scripts/validate_all_metrics.py (permanent gate)

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
            n.emission for n in neurons if n.incentive > 0 and n.dividends == 0
        ]

        if not miner_emissions or alpha_tao_price <= 0:
            return ROIEstimate(
                net_tao_yield_per_day=0.0,
                days_to_recoup=float("inf"),
                thirty_day_projected_tao=-registration_cost_tao,
                alpha_tao_rate=max(0.0, alpha_tao_price),
                earning_miners_count=len(miner_emissions),
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
            earning_miners_count=len(miner_emissions),
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

        Metric:
            name: Taoflow Health
            status: NEEDS_VALIDATION
            hypothesis: |
                Under Bittensor's Taoflow model, subnets compete for stake. When stakers
                leave (negative flow), emission share decreases, causing more stakers to
                leave → death spiral. 3+ consecutive negative days = warning. 7+ days with
                >25% emission decline = critical.
            formula: |
                daily_flows = [stake[i] - stake[i-1] for each day]
                consecutive_negative = count from most recent backward
                IF consecutive_negative >= 7 AND emission declined > 25%: DEATH_SPIRAL_RISK
                ELIF consecutive_negative >= 3: DECLINING
                ELSE: HEALTHY
            usefulness_mining: Don't enter a dying subnet — registration cost is wasted if emission drops to zero
            usefulness_staking: CRITICAL — primary risk signal for validators. Death spiral = staked TAO earns less and less
            usefulness_risk: Detect declining subnets early → exit before the crowd
            output_range: "Enum {HEALTHY, DECLINING, DEATH_SPIRAL_RISK}"
            known_issues: |
                - CURRENTLY DORMANT — always returns HEALTHY because we don't accumulate stake history yet
                - Needs 7+ days of history before becoming meaningful
                - Passes empty lists ([], []) in production
            assumptions: |
                - Is 3 days the right threshold for DECLINING?
                - Is 25% emission decline the right threshold for DEATH_SPIRAL?
                - To activate: accumulate daily total_validator_stake and total_emission per subnet

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

        Metric:
            name: Miner Churn
            status: HYPOTHESIS
            hypothesis: |
                High churn = competitive subnet where weak miners get replaced quickly.
                Low churn = stable subnet where incumbents are entrenched. The trend tells
                you if competition is heating up or cooling down.
            formula: |
                new_miners = current_hotkeys - previous_hotkeys
                departed_miners = previous_hotkeys - current_hotkeys
                churn_rate = (|new| + |departed|) / |current|
                avg_lifespan = mean(current_block - block_at_registration) for active
                net_change_pct = (|new| - |departed|) / |current|
                IF net_change_pct > 0.05 → INCREASING
                ELIF < -0.05 → DECREASING
                ELSE → STABLE
            usefulness_mining: High churn + INCREASING = dangerous (deregistered fast). Low churn + STABLE = incumbents safe.
            usefulness_staking: High churn means more registration fees burned → good for subnet economics
            usefulness_risk: DECREASING competition = opportunity window to enter
            output_range: "churn_rate: [0.0, 1.0]; trend: {INCREASING, STABLE, DECREASING}"
            known_issues: |
                - Requires previous-day snapshot for comparison (first day has no baseline)
                - Doesn't distinguish voluntary exit from deregistration
            assumptions: |
                - Is 5% net change the right threshold for INCREASING/DECREASING?
                - Should we weight by emission (losing a top miner vs losing a zero-earner)?

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
        churn_rate = max(0.0, churn_rate)

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

        Metric:
            name: Validator Landscape
            status: HYPOTHESIS
            hypothesis: |
                The validator landscape determines how competitive staking is. A concentrated
                subnet (one whale validator with >50% stake) means small stakers earn
                proportionally less. A distributed subnet means more equal opportunity.
            formula: |
                validators = [n for n if n.dividends > 0]
                total_stake = sum(v.stake)
                top_1_share = max(v.stake) / total_stake
                top_3_share = sum(top 3 stakes) / total_stake
                concentrated = top_1_share > 0.5
                net_yield = avg(v.emission) × alpha_tao_price
            usefulness_mining: Concentrated validators may have biased scoring (single point of failure)
            usefulness_staking: Avoid concentrated subnets where one whale dominates dividends
            usefulness_risk: If dominant validator leaves, subnet scoring could change dramatically
            output_range: "active_validators: int; stake shares: [0, 1]; concentrated: bool"
            known_issues: |
                - avg_validator_activity_blocks always returns 0 (blocks_since_last_step is subnet-level, not per-neuron)
                - net_yield uses average emission which may be skewed by inactive validators
            assumptions: |
                - Is 50% the right threshold for "concentrated"?
                - Does concentration actually reduce small-staker returns linearly?

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
                avg_vtrust=0.0,
                min_vtrust=0.0,
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

        # VTrust: how well validators align with consensus
        vtrust_values = [v.validator_trust for v in validators]
        avg_vtrust = sum(vtrust_values) / len(vtrust_values)
        min_vtrust = min(vtrust_values)

        return ValidatorLandscape(
            active_validators=len(validators),
            total_validator_stake=total_stake,
            top_1_stake_share=min(1.0, top_1_share),
            top_3_stake_share=min(1.0, top_3_share),
            concentrated=top_1_share > 0.5,
            avg_validator_activity_blocks=avg_activity,
            net_tao_yield_per_validator_per_day=net_yield,
            avg_vtrust=avg_vtrust,
            min_vtrust=min_vtrust,
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

        Metric:
            name: Validator Opportunity Assessment
            status: HYPOTHESIS
            hypothesis: |
                Validators earn dividends proportional to their stake share. The minimum
                effective stake tells you how much TAO you need to earn anything. The daily
                ROI tells you the return rate on your capital. This is the KEY metric for
                staking decisions.
            formula: |
                avg_emission = sum(v.emission) / len(validators)
                net_tao_yield = avg_emission × alpha_tao_price
                min_effective_stake = validators_by_dividends[10th percentile].stake
                daily_roi = net_tao_yield / avg_stake
                slots_available = max_validators - len(validators)
                concentrated = max(v.stake) / total_stake > 0.5
            usefulness_mining: Concentrated validators may have biased scoring
            usefulness_staking: PRIMARY metric — directly answers "where should I stake my TAO?"
            usefulness_risk: min_effective_stake tells you if your capital is sufficient
            output_range: "viable: bool; net_tao_yield: TAO/day; daily_roi_percent: %"
            known_issues: |
                - Uses average emission which may be skewed
                - Bottom 10% threshold for min_effective_stake is arbitrary
                - Doesn't account for validator commission rates
            assumptions: |
                - Does avg_emission × alpha_price accurately predict validator earnings?
                - Is bottom 10% the right minimum viable stake threshold?
                - Does stake concentration affect returns linearly?
                - Are there subnets where small validators earn disproportionately?

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
    def compute_competitive_density(neurons: list[Neuron], max_uids: int = 256) -> float:
        """Compute competitive density as earning miners / max UID slots.

        Metric:
            name: Competitive Density
            status: PROVEN
            hypothesis: |
                Occupancy rate: what fraction of available slots have earning miners.
                High density = crowded, hard to stand out. Low = room to enter.
            formula: |
                earning_miners = count(miners where emission > 0)
                density = earning_miners / max_uids
            output_range: "[0.0, 1.0] — higher = more competitive"
            validated_against: |
                - Live chain metagraph (5 subnets, ±7%) — 2026-06-03
                - Temporal differences expected (WTA subnets flip between tempos)
        """
        miners = [n for n in neurons if n.incentive > 0 or not n.is_validator]
        if not miners or max_uids <= 0:
            return 0.0

        earning_miners = sum(1 for m in miners if m.emission > 0)
        return earning_miners / max_uids

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

        Metric:
            name: Emission Trend
            status: PROVEN
            hypothesis: |
                Emission trends indicate subnet health. Increasing emission = subnet is
                gaining stake (Taoflow allocates more emission to subnets with more stake).
                Declining = stakers are leaving.
            formula: |
                change_percent = (current - previous) / previous
                IF change > 0.01 → "increasing"
                ELIF change < -0.01 → "declining"
                ELSE → "stable"
                seven_day_trend = (day7 - day1) / day1  (when history available)
            usefulness_mining: Enter subnets with increasing emission (growing pie). Avoid declining.
            usefulness_staking: Same — increasing emission means your stake earns more over time
            usefulness_risk: Used in attractiveness score (weight 0.10)
            output_range: "direction: {increasing, stable, declining}; change_percent: (-∞, ∞)"
            known_issues: None — simple day-over-day comparison
            assumptions: |
                - Is 1% the right threshold for "meaningful" change?
                - Should we use exponential moving average instead of simple comparison?

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


    # =========================================================================
    # Staking Intelligence: Validator Yield Per TAO Staked
    # =========================================================================

    @staticmethod
    def compute_staking_yield(
        neurons: list[Neuron],
        alpha_tao_price: float,
        pool_tao_liquidity: float,
        stake_amount_tao: float = 10.0,
    ) -> dict:
        """Compute net TAO yield for staking on a subnet.

        Metric:
            name: Staking Yield (Net TAO Return)
            status: HYPOTHESIS
            hypothesis: |
                When you stake on a subnet, you buy alpha tokens and stake them.
                Your dividend share is proportional to your stake (S = AS + TS).
                Yield is earned in alpha, which must be converted back to TAO.
                Net return accounts for entry slippage, exit slippage, and alpha price risk.
            formula: |
                alpha_bought = stake_tao / alpha_price × (1 - entry_slippage)
                your_share = alpha_bought / (total_validator_alpha_stake + alpha_bought)
                daily_alpha_yield = total_validator_emission_daily × your_share
                daily_tao_net = daily_alpha_yield × alpha_price × (1 - exit_slippage)
                apy = daily_tao_net × 365 / stake_tao × 100
                break_even_depreciation = annual_yield / principal_value
            usefulness_mining: Not directly relevant
            usefulness_staking: PRIMARY metric — answers "where should I stake my TAO for best return?"
            usefulness_risk: break_even_depreciation shows how much alpha can drop before you lose money
            output_range: "apy: (-100%, ∞); daily_tao_net: [0, ∞)"
            known_issues: |
                - Assumes dividends proportional to S (validated on SN95 and SN1, D/S_share ≈ 1.0)
                - Slippage is conservative upper bound (constant product AMM)
                - Does not account for alpha price appreciation
                - Uses current alpha price for exit
            assumptions: |
                - Dividends remain proportional to stake (validated live)
                - Alpha price stays constant (conservative)
                - You stake via alpha (confirmed: no direct TAO staking on subnets)

        Args:
            neurons: All neurons in the subnet.
            alpha_tao_price: Current alpha/TAO exchange rate.
            pool_tao_liquidity: TAO in the AMM pool (for slippage).
            stake_amount_tao: Amount of TAO to stake (default 10).

        Returns:
            Dict with staking yield metrics.
        """
        validators = [n for n in neurons if n.dividends > 0]

        if not validators or alpha_tao_price <= 0:
            return {
                "viable": False,
                "net_apy_percent": 0.0,
                "daily_tao_net": 0.0,
                "entry_slippage": 0.0,
                "exit_slippage": 0.0,
                "total_validator_stake": 0.0,
                "active_validators": 0,
                "break_even_alpha_depreciation": 0.0,
            }

        total_alpha_stake = sum(v.alpha_stake for v in validators)
        total_emission = sum(v.emission for v in validators)  # already daily

        # Entry: buy alpha with TAO (with slippage)
        entry_slippage = MetricsEngine._estimate_slippage(
            stake_amount_tao / alpha_tao_price, alpha_tao_price, pool_tao_liquidity
        )
        alpha_bought = (stake_amount_tao / alpha_tao_price) * (1 - entry_slippage)

        # Your share of the validator pool
        your_share = alpha_bought / (total_alpha_stake + alpha_bought) if total_alpha_stake > 0 else 0

        # Daily yield in alpha
        daily_alpha_yield = total_emission * your_share

        # Exit: convert daily yield back to TAO
        exit_slippage = MetricsEngine._estimate_slippage(
            daily_alpha_yield, alpha_tao_price, pool_tao_liquidity
        )
        daily_tao_net = daily_alpha_yield * alpha_tao_price * (1 - exit_slippage)

        # APY
        apy = (daily_tao_net * 365 / stake_amount_tao * 100) if stake_amount_tao > 0 else 0

        # Break-even alpha depreciation
        principal_tao_value = alpha_bought * alpha_tao_price
        break_even = (daily_tao_net * 365 / principal_tao_value) if principal_tao_value > 0 else 0

        return {
            "viable": True,
            "net_apy_percent": apy,
            "daily_tao_net": daily_tao_net,
            "entry_slippage": entry_slippage,
            "exit_slippage": exit_slippage,
            "total_validator_stake": total_alpha_stake,
            "active_validators": len(validators),
            "break_even_alpha_depreciation": break_even,
        }

    # =========================================================================
    # Real 1D APY (from actual emission snapshots)
    # =========================================================================

    @staticmethod
    def compute_real_apy(
        total_validator_emission_daily: float,
        pool_tao_liquidity: float,
        alpha_price: float,
    ) -> float:
        """Compute real annualized alpha yield from actual daily emission data.

        Metric:
            name: Alpha APY (1D)
            status: PROVEN
            hypothesis: |
                Matches bittensor.ai per-staker simulation. When you stake TAO,
                it enters the pool and you receive alpha. Your share of validator
                dividends is proportional to your alpha vs the pool's total alpha.
                The pool alpha (pool_tao / alpha_price) is the correct denominator —
                NOT sum(mg.AS) which includes consensus-locked alpha beyond the pool.
            formula: |
                pool_alpha = pool_tao_liquidity / alpha_price
                daily_yield_rate = emission_daily / pool_alpha
                apr = daily_yield_rate × 365 × 100
            output_range: "[0.0, ~3000%) — typically 30% to 300% for active subnets"
            known_issues: |
                - Extrapolates one day to a year (volatile day = misleading APY)
                - Alpha APY ≠ TAO APY (alpha price fluctuates)
                - Does not subtract per-validator commission (reports gross pool APY)
                - bittensor.ai headline 'staker APY' includes price appreciation (higher than this)
            validated_against: |
                - Taostats compound formula (±20% tolerance) — scripts/archive/validate_formulas.py
                - Live chain metagraph (5 subnets, ±10%) — 2026-06-03
                - bittensor.ai per-staker simulation (SN44: 82-100% range matches)
        """
        if pool_tao_liquidity <= 0 or alpha_price <= 0 or total_validator_emission_daily <= 0:
            return 0.0
        pool_alpha = pool_tao_liquidity / alpha_price
        if pool_alpha < 100.0:
            return 0.0
        daily_yield_rate = total_validator_emission_daily / pool_alpha
        return daily_yield_rate * 365 * 100

    # =========================================================================
    # Net TAO Flow (30-day EMA)
    # =========================================================================

    @staticmethod
    def compute_net_tao_flow(stake_history: list[float]) -> dict:
        """Compute net TAO flow with 30-day exponential moving average.

        Metric:
            name: Net TAO Flow (EMA)
            status: PROVEN
            hypothesis: |
                Net TAO Flow measures staking inflows minus outflows. Since May 2026,
                this directly determines subnet emission allocation. A 30-day EMA
                smooths daily noise. Positive = growing subnet, negative = dying.
            formula: |
                daily_flows = [stake[i] - stake[i-1] for i in range(1, len)]
                EMA with half-life 30 days: alpha = 1 - exp(-ln(2)/30)
                ema = exponential_moving_average(daily_flows, alpha)
            output_range: "net_flow: (-∞, ∞) TAO/day; ema_flow: (-∞, ∞) smoothed"
        """
        if len(stake_history) < 2:
            return {"net_flow": 0.0, "ema_flow": 0.0, "days_of_data": len(stake_history)}

        # Compute daily flows
        daily_flows = [stake_history[i] - stake_history[i - 1]
                       for i in range(1, len(stake_history))]

        net_flow = daily_flows[-1] if daily_flows else 0.0

        # EMA with 30-day half-life: alpha = 1 - exp(-ln2/30) ≈ 0.0228
        import math
        alpha = 1.0 - math.exp(-math.log(2) / 30.0)

        ema = daily_flows[0]
        for flow in daily_flows[1:]:
            ema = alpha * flow + (1.0 - alpha) * ema

        return {"net_flow": net_flow, "ema_flow": ema, "days_of_data": len(stake_history)}

    # =========================================================================
    # Risk-Adjusted Attractiveness Score
    # =========================================================================

    @staticmethod
    def compute_attractiveness_score(
        net_tao_yield: float,
        emission_share: float,
        pool_depth_tao: float,
        self_mining_risk: float,
        net_flow_ema: float = 0.0,
    ) -> float:
        """Compute risk-adjusted attractiveness score.

        Metric:
            name: Attractiveness Score (Risk-Adjusted)
            status: HYPOTHESIS
            hypothesis: |
                Inspired by Taoculator's Subnet Health Score. Combines yield, flow,
                emission share, and pool depth with multiplicative self-mining penalty.
                Answers "should I enter this subnet?" not just "how much does it emit?"
            formula: |
                yield_score = min(net_tao_yield / 200, 1.0)  (200 TAO/day = ceiling)
                flow_score = sigmoid(net_flow_ema / 500)  (normalized to [0,1])
                emission_score = min(emission_share / 0.02, 1.0)  (2% share = max)
                depth_score = min(pool_depth_tao / 20000, 1.0)  (20k TAO = deep)
                raw = yield×0.30 + flow×0.25 + emission×0.25 + depth×0.20
                score = raw × (1.0 - self_mining_risk)
            output_range: "[0.0, 1.0]"
        """
        import math

        # Yield component (0-1): 200 TAO/day = perfect
        yield_score = min(max(net_tao_yield, 0.0) / 200.0, 1.0)

        # Flow component (0-1): sigmoid centered at 0, scaled by 500 TAO/day
        flow_score = 1.0 / (1.0 + math.exp(-net_flow_ema / 500.0))

        # Emission share component (0-1): 2% of network = perfect
        emission_score = min(max(emission_share, 0.0) / 0.02, 1.0)

        # Pool depth component (0-1): 20k TAO liquidity = deep enough
        depth_score = min(max(pool_depth_tao, 0.0) / 20000.0, 1.0)

        # Weighted combination
        raw = (yield_score * 0.30 + flow_score * 0.25 +
               emission_score * 0.25 + depth_score * 0.20)

        # Multiplicative self-mining penalty
        penalty = 1.0 - min(max(self_mining_risk, 0.0), 1.0)

        return max(0.0, min(1.0, raw * penalty))

    # =========================================================================
    # Validator Concentration Risk
    # =========================================================================

    @staticmethod
    def compute_validator_concentration_risk(
        active_validators: int,
        top_1_stake_share: float,
    ) -> dict:
        """Compute validator concentration risk as a standalone metric.

        Metric:
            name: Validator Concentration Risk
            status: PROVEN
            hypothesis: |
                Subnets with fewer validators or extreme stake concentration are
                fragile — if the dominant validator leaves, scoring collapses.
                This is independent of self-mining (a subnet can be concentrated
                but legitimate). Used for staking decisions.
            formula: |
                IF active_validators == 1: risk = 1.0
                ELIF top_1_stake_share > 0.9: risk = 0.7
                ELIF top_1_stake_share > 0.7: risk = 0.4
                ELIF top_1_stake_share > 0.5: risk = 0.2
                ELSE: risk = 0.0
            output_range: "risk: [0.0, 1.0]; tier: {critical, high, medium, low, healthy}"
        """
        if active_validators <= 1:
            risk = 1.0
            tier = "critical"
        elif top_1_stake_share > 0.9:
            risk = 0.7
            tier = "high"
        elif top_1_stake_share > 0.7:
            risk = 0.4
            tier = "medium"
        elif top_1_stake_share > 0.5:
            risk = 0.2
            tier = "low"
        else:
            risk = 0.0
            tier = "healthy"

        return {
            "risk": risk,
            "tier": tier,
            "active_validators": active_validators,
            "top_1_stake_share": top_1_stake_share,
        }

    # =========================================================================
    # Self-Mining Detection Heuristic
    # =========================================================================

    @staticmethod
    def compute_self_mining_risk(neurons: list[Neuron]) -> dict:
        """Detect subnets likely gaming emissions via self-mining or abandonment.

        Metric:
            name: Self-Mining Risk
            status: HYPOTHESIS
            hypothesis: |
                Subnets with a single miner, single validator, shared coldkeys, and
                low participant diversity are likely self-mining — the owner validates
                their own miner to capture emissions without real competition or work.
                Const (Bittensor co-founder) announced emission blocking for such subnets.
            formula: |
                signals = []
                risk = 0.0
                IF earning_miners <= 1: risk += 0.35, signal "single_or_no_earning_miner"
                IF active_validators == 1: risk += 0.25, signal "single_validator"
                IF miner_coldkeys ∩ validator_coldkeys ≠ ∅: risk += 0.25, signal "coldkey_overlap"
                IF unique_coldkeys / total_neurons < 0.3: risk += 0.15, signal "low_neuron_diversity"
            usefulness_mining: Avoid registering on subnets likely to have emissions blocked
            usefulness_staking: Avoid staking on subnets that may lose all emission
            usefulness_risk: Primary signal for "is this subnet legitimate?"
            output_range: "risk_score: [0.0, 1.0]; signals: list of triggered signal names"
            known_issues: |
                - Does not check on-chain subnet description or GitHub activity
                - Coldkey overlap is necessary but not sufficient (some legitimate subnets share coldkeys during bootstrap)
                - Owner cut percentage not included (requires hyperparams passed separately)
            assumptions: |
                - Are the signal weights (0.35, 0.25, 0.25, 0.15) well-calibrated?
                - Is coldkey overlap always suspicious, or only combined with other signals?
                - Should we add a time-based signal (subnet age vs activity)?
            validated_against: |
                - Manual spot-check: SN97=1.0, SN104=0.75 (known self-mining), SN44=0.0 (clean)
                - False positive fix validated: WTA subnets no longer trigger Signal 1

        Args:
            neurons: All neurons in the subnet.

        Returns:
            Dict with risk_score [0.0, 1.0], signals list, and diagnostic counts.
        """
        if not neurons:
            return {"risk_score": 0.0, "signals": [], "earning_miners": 0,
                    "active_validators": 0, "unique_coldkeys": 0}

        risk = 0.0
        signals: list[str] = []

        miners = [n for n in neurons if n.incentive > 0 or not n.is_validator]
        earning_miners = [m for m in miners if m.emission > 0]
        validators = [n for n in neurons if n.is_validator]

        # Signal 1: Single or no earning miner AND few validators (weight 0.35)
        # Many legitimate WTA subnets have only 1 earning miner by design.
        # Self-mining indicator: few earners AND few validators (< 3).
        if len(earning_miners) <= 1 and len(validators) <= 2:
            risk += 0.35
            signals.append("single_or_no_earning_miner")

        # Signal 2: Single validator (weight 0.25)
        if len(validators) == 1:
            risk += 0.25
            signals.append("single_validator")

        # Signal 3: Coldkey overlap between miners and validators (weight 0.25)
        # Only suspicious if MAJORITY of validators share coldkeys with miners
        miner_coldkeys = {m.coldkey for m in earning_miners}
        validator_coldkeys = {v.coldkey for v in validators}
        overlap = miner_coldkeys & validator_coldkeys
        if overlap and len(overlap) >= len(validator_coldkeys) * 0.5:
            risk += 0.25
            signals.append("coldkey_overlap")

        # Signal 4: Low neuron diversity (weight 0.15)
        # Only suspicious if extremely low (< 10%) — most subnets have 20-30% normally
        unique_coldkeys = len({n.coldkey for n in neurons})
        diversity = unique_coldkeys / len(neurons) if neurons else 1.0
        if diversity < 0.10:
            risk += 0.15
            signals.append("low_neuron_diversity")

        return {
            "risk_score": min(1.0, risk),
            "signals": signals,
            "earning_miners": len(earning_miners),
            "active_validators": len(validators),
            "unique_coldkeys": unique_coldkeys,
        }


