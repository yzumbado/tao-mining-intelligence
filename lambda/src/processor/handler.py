"""Processor Lambda handler — computes derived metrics from raw snapshots.

Triggered by SQS message (one per subnet per cycle). Reads raw data from S3,
runs MetricsEngine, stores derived metrics, updates split profiles in DynamoDB,
tracks hotkeys, and publishes completion to SNS.

Architecture decisions applied:
- Decision 11: Split profiles are single source of truth (no METRICS#latest)
- Decision 12: Tempo conversion happens here before calling MetricsEngine
- Decision 13: Taoflow returns HEALTHY when insufficient history
- Decision 14: Per-subnet FSM is best-effort (cycle counter is critical path)
"""

import json
import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import boto3

from src.config import PipelineConfig, get_config
from src.instrumentation import set_trace_id, instrument
from src.processor.metrics import MetricsEngine
from src.state.state_manager import StateManager
from src.storage.storage_layer import StorageLayer

logger = logging.getLogger("tao-pipeline")

# Module-level cold-start cache
_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_storage: Optional[StorageLayer] = None
_sns_client: Optional[Any] = None


def _init_clients() -> None:
    """Initialize AWS clients and config on cold start (cached)."""
    global _config, _state_manager, _storage, _sns_client
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)
    _storage = StorageLayer(_config)
    if _config.is_aws and _config.queue.subnet_processed_topic_arn:
        _sns_client = boto3.client("sns", region_name=_config.region)


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Processes a single subnet's raw data into derived metrics."""
    _init_clients()

    # Reset trace context immediately to avoid stale values from warm invocations
    set_trace_id("", "")

    # Parse SQS message
    try:
        record = event["Records"][0]
        body = json.loads(record["body"])
        netuid = body["netuid"]
        date = body["date"]
        cycle_id = body["cycle_id"]
        trace_id = body.get("trace_id", "")
    except (json.JSONDecodeError, KeyError, IndexError) as e:
        logger.error(f"Failed to parse SQS message: {e}")
        return {"status": "error", "netuid": 0, "error": f"malformed message: {e}"}

    set_trace_id(trace_id, cycle_id)

    with instrument("processor", "handle", netuid=netuid, cycle_id=cycle_id) as ctx:
        # Best-effort per-subnet state transition
        try:
            _state_manager.transition(netuid, "IDLE", "PROCESSING",
                                      metadata={"cycle_id": cycle_id})
        except Exception as e:
            logger.warning(f"Per-subnet state transition failed (best-effort): {e}")

        # Read raw metagraph snapshot
        snapshot = _storage.read_snapshot(
            _storage.get_date_path("raw/metagraph", date, netuid))
        if snapshot is None:
            _mark_error(netuid, cycle_id, "raw snapshot not found")
            return {"status": "error", "netuid": netuid, "cycle_id": cycle_id,
                    "error": "raw snapshot not found"}

        # Read supplementary data
        alpha_prices = _storage.read_snapshot(
            _storage.get_date_path("raw/alpha-prices", date, netuid))
        reg_costs = _storage.read_snapshot(
            _storage.get_date_path("raw/registration-costs", date, netuid))
        hyperparams = _storage.read_snapshot(
            _storage.get_date_path("raw/hyperparameters", date, netuid))

        # Read previous day snapshot for trend/churn
        prev_snapshot = _storage.get_previous_day_snapshot(netuid, date)

        # Extract subnet-specific data
        alpha_price, pool_tao, root_proportion = _extract_alpha_price(alpha_prices, netuid)
        reg_cost_tao = _extract_reg_cost(reg_costs, netuid)
        tempo = _extract_tempo(hyperparams)
        immunity_period = _extract_immunity_period(hyperparams)

        # Build Neuron objects with tempo-converted emissions
        from src.models.schemas import Neuron
        neurons_raw = snapshot.get("data", {}).get("neurons", [])
        tempos_per_day = 7200.0 / tempo
        neurons = _build_neurons(neurons_raw, tempos_per_day)

        # Compute all metrics
        metrics_computed = []
        current_block = snapshot.get("metadata", {}).get("source_block_number", 5000000)

        # Deregistration risk
        num_uids = snapshot.get("metadata", {}).get("num_uids", len(neurons))
        max_uids = snapshot.get("metadata", {}).get("max_uids", 256)
        dereg_risks = MetricsEngine.compute_deregistration_risk(
            neurons, current_block, immunity_period,
            recent_registrations_24h=_count_recent_registrations(neurons_raw, current_block),
            num_uids=num_uids,
            max_uids=max_uids)
        metrics_computed.append("deregistration_risk")

        # Competitive density
        competitive_density = MetricsEngine.compute_competitive_density(neurons)
        metrics_computed.append("competitive_density")

        # Reward distribution model
        emissions = [n.emission for n in neurons if n.emission > 0]
        reward_model, gini, top_3 = MetricsEngine.detect_reward_distribution_model(emissions)
        metrics_computed.append("reward_distribution")

        # ROI estimate (emissions already converted to daily by _build_neurons)
        roi = MetricsEngine.compute_roi_estimates(
            neurons, reg_cost_tao, alpha_price, pool_tao)
        metrics_computed.append("roi_estimate")

        # Emission trend
        prev_total = _get_previous_total_emission(prev_snapshot, tempos_per_day)
        current_total = sum(n.emission for n in neurons)
        emission_trend = MetricsEngine.compute_emission_trend(current_total, prev_total)
        metrics_computed.append("emission_trend")

        # Miner churn
        current_hotkeys = {n.hotkey for n in neurons if n.incentive > 0 or not n.is_validator}
        prev_hotkeys = _get_previous_hotkeys(prev_snapshot)
        churn = MetricsEngine.compute_miner_churn(
            current_hotkeys, prev_hotkeys,
            [{"block_at_registration": n.block_at_registration, "active": n.active}
             for n in neurons],
            current_block)
        metrics_computed.append("churn")

        # Taoflow health (graceful degradation — insufficient history returns HEALTHY)
        taoflow = MetricsEngine.compute_taoflow_health([], [])
        metrics_computed.append("taoflow_health")

        # Validator landscape
        validator_landscape = MetricsEngine.compute_validator_landscape(neurons, alpha_price)
        metrics_computed.append("validator_landscape")

        # Real 1D APY (from actual emission data)
        validators = [n for n in neurons if n.dividends > 0]
        total_val_emission = sum(v.emission for v in validators)
        total_val_stake = sum(v.alpha_stake for v in validators)
        real_apy = MetricsEngine.compute_real_apy(
            total_val_emission, total_val_stake, alpha_price, root_proportion=root_proportion)
        metrics_computed.append("real_apy")

        # Validator concentration risk (standalone metric for staking decisions)
        concentration_risk = MetricsEngine.compute_validator_concentration_risk(
            validator_landscape.active_validators, validator_landscape.top_1_stake_share)
        metrics_computed.append("concentration_risk")

        # Accumulate daily stake total for Net TAO Flow (one write per subnet per day)
        _store_daily_stake(netuid, date, total_val_stake)

        # Self-mining risk detection
        self_mining_risk = MetricsEngine.compute_self_mining_risk(neurons)
        metrics_computed.append("self_mining_risk")

        # Store derived metrics to S3
        derived_data = _build_derived_output(
            netuid, date, dereg_risks, competitive_density, emission_trend,
            roi, reward_model, gini, top_3, taoflow, churn, validator_landscape,
            self_mining_risk=self_mining_risk,
            concentration_risk=concentration_risk,
            real_apy=real_apy,
            pool_tao_liquidity=pool_tao,
            source_block_number=current_block)
        _storage.store_snapshot(
            _storage.get_date_path("derived/metrics", date, netuid), derived_data)

        # Write split profiles to DynamoDB
        _write_split_profiles(netuid, neurons, reward_model, gini, top_3,
                              validator_landscape, date,
                              self_mining_risk=self_mining_risk)

        # Track hotkeys
        _track_hotkeys(netuid, date, neurons, prev_snapshot)

        # Increment cycle progress (critical path)
        _state_manager.increment_cycle_progress(cycle_id)

        # Best-effort per-subnet state → COMPLETE
        try:
            _state_manager.transition(netuid, "PROCESSING", "COMPLETE")
        except Exception as e:
            logger.warning(f"Per-subnet COMPLETE transition failed (best-effort): {e}")

        # Publish SNS completion (legacy path — kept for backward compat)
        sns_published = _publish_completion(netuid, date, cycle_id, trace_id)

        # Invoke Aggregator to recompute rankings (AD18: rankings are a live view)
        _invoke_aggregator(netuid, date, cycle_id, trace_id)

        # Schedule next collection for this subnet (self-perpetuating loop)
        next_scheduled = _schedule_next_collection(netuid, tempo)

        ctx["metrics_computed"] = metrics_computed
        ctx["sns_published"] = sns_published
        ctx["next_scheduled"] = next_scheduled

        return {
            "status": "complete",
            "netuid": netuid,
            "cycle_id": cycle_id,
            "trace_id": trace_id,
            "metrics_computed": metrics_computed,
            "sns_published": sns_published,
            "next_scheduled": next_scheduled,
        }


# ---------------------------------------------------------------------------
# Data extraction helpers
# ---------------------------------------------------------------------------


def _build_neurons(neurons_raw: list[dict], tempos_per_day: float):
    """Build Neuron model objects with emissions converted to daily."""
    from src.models.schemas import Neuron
    neurons = []
    for n in neurons_raw:
        neurons.append(Neuron(
            uid=n["uid"],
            hotkey=n["hotkey"],
            coldkey=n["coldkey"],
            stake=n.get("stake", 0.0),
            incentive=n.get("incentive", 0.0),
            emission=n.get("emission", 0.0) * tempos_per_day,
            consensus=n.get("consensus", 0.0),
            validator_trust=n.get("validator_trust", 0.0),
            dividends=n.get("dividends", 0.0),
            active=n.get("active", True),
            alpha_stake=n.get("alpha_stake", 0.0),
            total_stake=n.get("total_stake", 0.0),
            block_at_registration=n.get("block_at_registration", 0),
        ))
    return neurons


def _extract_alpha_price(alpha_prices: Optional[dict], netuid: int) -> tuple[float, float, float]:
    """Extract alpha/TAO price, pool liquidity, and root_proportion for a subnet."""
    if not alpha_prices:
        return 0.0, 0.0, 0.0
    data = alpha_prices.get("data", {})
    # Per-subnet format: {data: {alpha_tao_price: ..., pool_tao_liquidity: ..., root_proportion: ...}}
    if "alpha_tao_price" in data:
        return (data.get("alpha_tao_price", 0.0),
                data.get("pool_tao_liquidity", 0.0),
                data.get("root_proportion", 0.0))
    # Consolidated format: {data: {prices: [{netuid: N, ...}]}}
    for p in data.get("prices", []):
        if p.get("netuid") == netuid:
            return (p.get("alpha_tao_price", 0.0),
                    p.get("pool_tao_liquidity", 0.0),
                    p.get("root_proportion", 0.0))
    return 0.0, 0.0, 0.0


def _extract_reg_cost(reg_costs: Optional[dict], netuid: int) -> float:
    """Extract registration cost in TAO for a specific subnet."""
    if not reg_costs:
        return 0.0
    data = reg_costs.get("data", {})
    # Per-subnet format: {data: {registration_cost_tao: ...}}
    if "registration_cost_tao" in data:
        return data.get("registration_cost_tao", 0.0)
    # Consolidated format: {data: {costs: [{netuid: N, ...}]}}
    for c in data.get("costs", []):
        if c.get("netuid") == netuid:
            return c.get("registration_cost_tao", 0.0)
    return 0.0


def _extract_tempo(hyperparams: Optional[dict]) -> int:
    """Extract tempo from hyperparameters, default 360. Minimum 1 to avoid division by zero."""
    if not hyperparams:
        return 360
    return max(1, hyperparams.get("data", {}).get("tempo", 360))


def _extract_immunity_period(hyperparams: Optional[dict]) -> int:
    """Extract immunity period from hyperparameters, default 7200."""
    if not hyperparams:
        return 7200
    return hyperparams.get("data", {}).get("immunity_period", 7200)


def _store_daily_stake(netuid: int, date: str, total_stake: float) -> None:
    """Store daily stake total for Net TAO Flow computation."""
    try:
        _state_manager.store_daily_stake(netuid, date, total_stake)
    except Exception as e:
        logger.warning(f"Failed to store daily stake for SN{netuid}: {e}")



def _count_recent_registrations(neurons_raw: list[dict], current_block: int) -> int:
    """Count neurons registered in the last ~24h (7200 blocks)."""
    count = 0
    for n in neurons_raw:
        blocks_since = current_block - n.get("block_at_registration", 0)
        if 0 < blocks_since < 7200:
            count += 1
    return count


def _get_previous_total_emission(prev_snapshot: Optional[dict], tempos_per_day: float) -> float:
    """Get total emission from previous day snapshot, converted to daily."""
    if not prev_snapshot:
        return 0.0
    neurons = prev_snapshot.get("data", {}).get("neurons", [])
    return sum(n.get("emission", 0.0) * tempos_per_day for n in neurons)


def _get_previous_hotkeys(prev_snapshot: Optional[dict]) -> set[str]:
    """Extract miner hotkeys from previous day snapshot."""
    if not prev_snapshot:
        return set()
    neurons = prev_snapshot.get("data", {}).get("neurons", [])
    return {n["hotkey"] for n in neurons
            if n.get("incentive", 0) > 0 or n.get("dividends", 0) == 0}


# ---------------------------------------------------------------------------
# Output builders
# ---------------------------------------------------------------------------


def _build_derived_output(netuid, date, dereg_risks, competitive_density,
                          emission_trend, roi, reward_model, gini, top_3,
                          taoflow, churn, validator_landscape,
                          self_mining_risk: Optional[dict] = None,
                          concentration_risk: Optional[dict] = None,
                          real_apy: float = 0.0,
                          pool_tao_liquidity: float = 0.0,
                          source_block_number: int = 0) -> dict:
    """Build the derived metrics JSON structure for S3 storage."""
    now = datetime.now(timezone.utc).isoformat()
    return {
        "metadata": {
            "netuid": netuid,
            "source_snapshot_date": date,
            "processed_at": now,
            "computation_timestamp": now,
            "source_block_number": source_block_number,
            "schema_version": "1.0.0",
            "pipeline_version": "1.0.0",
        },
        "data": {
            "deregistration_risk": [
                {"uid": r.uid, "hotkey": r.hotkey, "risk_score": r.risk_score,
                 "emission_rank": r.emission_rank, "immune": r.immune}
                for r in dereg_risks
            ],
            "competitive_density": competitive_density,
            "emission_trend": {
                "current_total_emission": emission_trend.current_total_emission,
                "previous_total_emission": emission_trend.previous_total_emission,
                "change_percent": emission_trend.change_percent,
                "direction": emission_trend.direction,
            },
            "roi_estimate": {
                "net_tao_yield_per_day": roi.net_tao_yield_per_day,
                "days_to_recoup": roi.days_to_recoup,
                "thirty_day_projected_tao": roi.thirty_day_projected_tao,
                "alpha_tao_rate": roi.alpha_tao_rate,
                "pool_tao_liquidity": pool_tao_liquidity,
                "slippage_estimate_percent": roi.slippage_estimate_percent,
                "hold_vs_swap_recommendation": roi.hold_vs_swap_recommendation.value,
                "confidence": roi.confidence.value,
            },
            "reward_distribution": {
                "model": reward_model.value,
                "gini_coefficient": gini,
                "top_3_concentration": top_3,
            },
            "taoflow_health": {
                "status": taoflow.status.value,
                "net_staking_flow_tao": taoflow.net_staking_flow_tao,
                "consecutive_negative_days": taoflow.consecutive_negative_days,
            },
            "churn": {
                "daily_churn_rate": churn.daily_churn_rate,
                "new_registrations": churn.new_registrations,
                "deregistrations": churn.deregistrations,
                "average_miner_lifespan_blocks": churn.average_miner_lifespan_blocks,
                "competition_trend": churn.competition_trend.value,
            },
            "validator_landscape": {
                "active_validators": validator_landscape.active_validators,
                "total_validator_stake": validator_landscape.total_validator_stake,
                "top_1_stake_share": validator_landscape.top_1_stake_share,
                "top_3_stake_share": validator_landscape.top_3_stake_share,
                "concentrated": validator_landscape.concentrated,
                "net_tao_yield_per_validator_per_day": validator_landscape.net_tao_yield_per_validator_per_day,
                "avg_vtrust": validator_landscape.avg_vtrust,
                "min_vtrust": validator_landscape.min_vtrust,
            },
            "self_mining_risk": self_mining_risk or {"risk_score": 0.0, "signals": []},
            "concentration_risk": concentration_risk or {"risk": 0.0, "tier": "healthy"},
            "real_apy_percent": real_apy,
        },
    }


# ---------------------------------------------------------------------------
# DynamoDB profile writes
# ---------------------------------------------------------------------------


def _write_split_profiles(netuid: int, neurons, reward_model, gini, top_3,
                          validator_landscape, date: str,
                          self_mining_risk: Optional[dict] = None) -> None:
    """Write all 5 split profiles to DynamoDB via StateManager."""
    now = datetime.now(timezone.utc).isoformat()

    # Build top miners for winner profile
    miners = sorted([n for n in neurons if n.incentive > 0],
                    key=lambda n: n.emission, reverse=True)[:5]
    total_emission = sum(n.emission for n in neurons if n.incentive > 0)
    top_miners = [{
        "hotkey": m.hotkey[:12] + "...",
        "uid": m.uid,
        "emission_share": (m.emission / total_emission) if total_emission > 0 else 0.0,
        "stake": m.stake,
        "blocks_registered": m.block_at_registration,
        "incentive": m.incentive,
    } for m in miners]

    profiles = {
        "basic": {
            "netuid": netuid,
            "reward_model": reward_model.value,
            "gini_coefficient": gini,
            "top_3_concentration": top_3,
            "processed_at": now,
            "last_updated": now,
        },
        "winner": {
            "netuid": netuid,
            "top_miners": top_miners,
            "last_updated": now,
        },
        "validator": {
            "netuid": netuid,
            "active_validators": validator_landscape.active_validators,
            "total_validator_stake": validator_landscape.total_validator_stake,
            "top_1_stake_share": validator_landscape.top_1_stake_share,
            "top_3_stake_share": validator_landscape.top_3_stake_share,
            "concentrated": validator_landscape.concentrated,
            "net_tao_yield_per_validator_per_day": validator_landscape.net_tao_yield_per_validator_per_day,
            "last_updated": now,
        },
        "intelligence": {
            "netuid": netuid,
            "anomalies": [],
            "strategy_observations": [],
            "risk_factors": [],
            "self_mining_risk": self_mining_risk or {"risk_score": 0.0, "signals": []},
            "last_updated": now,
        },
        "composability": {
            "netuid": netuid,
            "dependencies": [],
            "dependents": [],
            "composability_score": 0.0,
            "last_updated": now,
        },
    }

    _state_manager.write_subnet_profiles(netuid, profiles)


# ---------------------------------------------------------------------------
# Hotkey tracking
# ---------------------------------------------------------------------------


def _track_hotkeys(netuid: int, date: str, neurons, prev_snapshot: Optional[dict]) -> None:
    """Track earnings and detect deregistrations for watched hotkeys."""
    tracked = _state_manager.get_tracked_hotkeys()
    if not tracked:
        return

    current_hotkey_map = {n.hotkey: n for n in neurons}

    for hotkey in tracked:
        if hotkey in current_hotkey_map:
            neuron = current_hotkey_map[hotkey]
            _state_manager.record_hotkey_snapshot(hotkey, date, [{
                "netuid": netuid,
                "uid": neuron.uid,
                "emission": neuron.emission,
                "incentive": neuron.incentive,
                "rank": _get_emission_rank(neuron, neurons),
            }])


def _get_emission_rank(neuron, neurons) -> int:
    """Get a neuron's emission rank (0 = highest)."""
    miners = sorted([n for n in neurons if n.incentive > 0],
                    key=lambda n: n.emission, reverse=True)
    for i, m in enumerate(miners):
        if m.hotkey == neuron.hotkey:
            return i
    return len(miners)


# ---------------------------------------------------------------------------
# SNS publishing
# ---------------------------------------------------------------------------


def _invoke_aggregator(netuid: int, date: str, cycle_id: str, trace_id: str) -> None:
    """Invoke the Finalizer/Aggregator Lambda to recompute rankings.

    AD18: Rankings are a live view — recomputed after each subnet update.
    Best-effort: if invocation fails, rankings are stale but not lost.
    """
    if not _config.is_aws:
        return

    aggregator_arn = os.environ.get("AGGREGATOR_ARN", "")
    if not aggregator_arn:
        return

    try:
        lambda_client = boto3.client("lambda", region_name=_config.region)
        lambda_client.invoke(
            FunctionName=aggregator_arn,
            InvocationType="Event",  # Async — don't wait for response
            Payload=json.dumps({"date": date, "cycle_id": cycle_id,
                                "trace_id": trace_id, "trigger_netuid": netuid}).encode(),
        )
    except Exception as e:
        logger.warning(f"Failed to invoke Aggregator (best-effort): {e}")


def _schedule_next_collection(netuid: int, tempo: int) -> bool:
    """Create a one-time EventBridge schedule for the next collection of this subnet.

    The delay is max(min_refresh_interval, min(tempo_seconds, max_staleness)).
    Schedule self-deletes after firing (ActionAfterCompletion=DELETE).
    """
    if not _config.is_aws:
        return False

    try:
        scheduler = boto3.client("scheduler", region_name=_config.region)
        refresh_policy = _state_manager.get_refresh_policy()

        tempo_seconds = tempo * 12  # blocks × 12s per block
        max_staleness_seconds = refresh_policy["max_staleness_hours"] * 3600
        min_refresh_seconds = refresh_policy["min_refresh_interval_minutes"] * 60

        delay_seconds = max(min_refresh_seconds, min(tempo_seconds, max_staleness_seconds))
        next_run = datetime.now(timezone.utc) + timedelta(seconds=delay_seconds)

        collector_arn = os.environ.get("SUBNET_COLLECTOR_ARN", "")
        scheduler_role_arn = os.environ.get("SCHEDULER_ROLE_ARN", "")

        if not collector_arn or not scheduler_role_arn:
            logger.warning("SUBNET_COLLECTOR_ARN or SCHEDULER_ROLE_ARN not set, skipping schedule")
            return False

        schedule_name = f"tao-subnet-{netuid}"

        scheduler.create_schedule(
            Name=schedule_name,
            GroupName="default",
            ScheduleExpression=f"at({next_run.strftime('%Y-%m-%dT%H:%M:%S')})",
            ScheduleExpressionTimezone="UTC",
            FlexibleTimeWindow={"Mode": "OFF"},
            Target={
                "Arn": collector_arn,
                "RoleArn": scheduler_role_arn,
                "Input": json.dumps({"netuid": netuid}),
            },
            ActionAfterCompletion="DELETE",
        )
        logger.info(f"Scheduled next collection for SN{netuid} at {next_run.isoformat()} "
                    f"(delay={delay_seconds}s, tempo={tempo})")
        return True
    except Exception as e:
        logger.warning(f"Failed to schedule next collection for SN{netuid}: {e}")
        return False


def _publish_completion(netuid: int, date: str, cycle_id: str, trace_id: str) -> bool:
    """Publish completion message to SNS topic."""
    if not _sns_client or not _config.queue.subnet_processed_topic_arn:
        return False

    message = json.dumps({
        "netuid": netuid,
        "date": date,
        "cycle_id": cycle_id,
        "trace_id": trace_id,
        "status": "complete",
    })

    try:
        _sns_client.publish(
            TopicArn=_config.queue.subnet_processed_topic_arn,
            Message=message,
            Subject=f"subnet-{netuid}-processed",
        )
        return True
    except Exception as e:
        logger.error(f"Failed to publish SNS for netuid={netuid}: {e}")
        return False


# ---------------------------------------------------------------------------
# Error handling
# ---------------------------------------------------------------------------


def _mark_error(netuid: int, cycle_id: str, error: str) -> None:
    """Mark subnet as errored (best-effort)."""
    try:
        _state_manager.transition(netuid, "PROCESSING", "ERROR_RETRYABLE",
                                  metadata={"error": error[:500], "cycle_id": cycle_id})
    except Exception:
        pass
