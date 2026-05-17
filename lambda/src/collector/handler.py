"""Collector Lambda handler — daily data collection from Bittensor network.

Entry point for the daily collection cycle. Triggered by EventBridge schedule.
Collects metagraphs, registration costs, hyperparameters, alpha prices, and
TAO/USD price for all active subnets on the Bittensor network.

Architecture:
- AsyncSubtensor for async chain queries
- Semaphore-based concurrency control
- Circuit breaker to fail fast on endpoint outages
- Per-subnet timeout to prevent single-subnet hangs
- Graceful shutdown when Lambda timeout approaches
"""

import asyncio
import json
import logging
import os
from datetime import datetime, timezone
from typing import Any, Optional

import boto3
import requests
from bittensor import AsyncSubtensor

from src.circuit_breaker import (
    CircuitBreaker,
    DEFAULT_METAGRAPH_TIMEOUT_SECONDS,
    DEFAULT_PRICE_API_TIMEOUT_SECONDS,
    DEFAULT_QUERY_TIMEOUT_SECONDS,
    with_timeout,
)
from src.config import PipelineConfig, get_config
from src.instrumentation import get_trace_id, init_tracing, instrument
from src.state.state_manager import StateManager
from src.storage.storage_layer import StorageLayer
from src.validation import validate_alpha_prices, validate_metagraph, validate_registration_cost

logger = logging.getLogger("tao-pipeline")

# ---------------------------------------------------------------------------
# Module-level cold-start cache
# ---------------------------------------------------------------------------

_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_storage: Optional[StorageLayer] = None
_sqs_client: Optional[Any] = None
_ssm_client: Optional[Any] = None
_coingecko_api_key: Optional[str] = None

# Concurrency and resilience settings
CONCURRENCY_LIMIT = int(os.environ.get("CONCURRENCY_LIMIT", "32"))
GRACEFUL_SHUTDOWN_THRESHOLD_MS = 60_000  # Stop work when <60s remaining


# ---------------------------------------------------------------------------
# Cold-start initialization
# ---------------------------------------------------------------------------


def _init_clients() -> None:
    """Initialize AWS clients and config on cold start (cached)."""
    global _config, _state_manager, _storage, _sqs_client, _ssm_client, _coingecko_api_key

    if _config is not None:
        return

    _config = get_config()
    _state_manager = StateManager(_config)
    _storage = StorageLayer(_config)

    if _config.is_aws:
        _sqs_client = boto3.client("sqs", region_name=_config.region)
        _ssm_client = boto3.client("ssm", region_name=_config.region)
        _coingecko_api_key = _fetch_api_key()


def _fetch_api_key() -> Optional[str]:
    """Fetch CoinGecko API key from Parameter Store (cold-start only).

    Returns:
        API key string, or None if not configured.
    """
    param_name = os.environ.get("COINGECKO_API_KEY_PARAM", "/tao-pipeline/coingecko-api-key")
    try:
        resp = _ssm_client.get_parameter(Name=param_name, WithDecryption=True)
        return resp["Parameter"]["Value"]
    except Exception as e:
        logger.warning(f"Could not fetch CoinGecko API key from Parameter Store: {type(e).__name__}")
        return None


# ---------------------------------------------------------------------------
# Lambda entry point
# ---------------------------------------------------------------------------


def handle(event: dict, context) -> dict:
    """Lambda entry point. Called by AWS Lambda runtime.

    Args:
        event: EventBridge scheduled event payload.
        context: Lambda context object with get_remaining_time_in_millis().

    Returns:
        Summary dict with collection results.
    """
    return asyncio.run(_async_handle(event, context))


async def _async_handle(event: dict, context) -> dict:
    """Async implementation of the Lambda handler.

    Steps:
    1. Initialize clients (cached on cold start)
    2. Determine cycle_id and init tracing
    3. Claim cycle (idempotency check)
    4. Discover active subnets from chain
    5. Collect metagraphs concurrently with circuit breaker
    6. Collect supplementary data (reg costs, hyperparams, alpha prices, TAO price)
    7. Validate and store raw snapshots
    8. Publish SQS messages for successfully collected subnets
    9. Return summary
    """
    _init_clients()

    cycle_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    trace_id = init_tracing(cycle_id)

    with instrument("collector", "handle", cycle_id=cycle_id) as ctx:
        # --- Idempotency check ---
        netuids = await _discover_subnets()
        if not netuids:
            ctx["status_detail"] = "no_subnets_discovered"
            return {"cycle_id": cycle_id, "status": "no_subnets", "subnets_collected": 0}

        claimed = _state_manager.claim_cycle(cycle_id, subnets_total=len(netuids))
        if not claimed:
            ctx["status_detail"] = "cycle_already_claimed"
            return {"cycle_id": cycle_id, "status": "duplicate", "subnets_collected": 0}

        # --- Collect metagraphs concurrently ---
        semaphore = asyncio.Semaphore(CONCURRENCY_LIMIT)
        circuit_breaker = CircuitBreaker(failure_threshold=5)

        metagraph_results = await _collect_all_metagraphs(
            netuids=netuids,
            cycle_id=cycle_id,
            semaphore=semaphore,
            circuit_breaker=circuit_breaker,
            context=context,
        )

        successful_netuids = [n for n, data in metagraph_results.items() if data is not None]
        failed_netuids = [n for n, data in metagraph_results.items() if data is None]

        # --- Collect supplementary data ---
        if successful_netuids and _has_time_remaining(context):
            await _collect_supplementary_data(
                netuids=successful_netuids,
                cycle_id=cycle_id,
                context=context,
            )

        # --- Publish SQS messages for successful subnets ---
        published_count = 0
        if successful_netuids and _has_time_remaining(context):
            published_count = await _publish_processing_messages(
                netuids=successful_netuids,
                cycle_id=cycle_id,
                trace_id=trace_id,
            )

        # --- Update active subnets in state ---
        _state_manager.update_active_subnets(netuids)

        ctx["subnets_total"] = len(netuids)
        ctx["subnets_collected"] = len(successful_netuids)
        ctx["subnets_failed"] = len(failed_netuids)
        ctx["messages_published"] = published_count
        ctx["circuit_breaker_status"] = circuit_breaker.status

        return {
            "cycle_id": cycle_id,
            "trace_id": trace_id,
            "status": "complete",
            "subnets_total": len(netuids),
            "subnets_collected": len(successful_netuids),
            "subnets_failed": len(failed_netuids),
            "failed_netuids": failed_netuids,
            "messages_published": published_count,
        }


# ---------------------------------------------------------------------------
# Subnet discovery
# ---------------------------------------------------------------------------


async def _discover_subnets() -> list[int]:
    """Discover all active subnets from the Bittensor network.

    Returns:
        Sorted list of active subnet netuids.
    """
    with instrument("collector", "discover_subnets") as ctx:
        async with AsyncSubtensor() as sub:
            netuids = await with_timeout(
                sub.get_all_subnets_netuid(),
                timeout_seconds=DEFAULT_QUERY_TIMEOUT_SECONDS,
                operation_name="get_all_subnets_netuid",
            )
        ctx["subnet_count"] = len(netuids)
        return sorted(netuids)


# ---------------------------------------------------------------------------
# Metagraph collection
# ---------------------------------------------------------------------------


async def _collect_all_metagraphs(
    netuids: list[int],
    cycle_id: str,
    semaphore: asyncio.Semaphore,
    circuit_breaker: CircuitBreaker,
    context: Any,
) -> dict[int, Optional[dict]]:
    """Collect metagraphs for all subnets concurrently.

    Uses semaphore for concurrency control and circuit breaker for fast failure.
    Checks remaining Lambda time before each subnet.

    Args:
        netuids: List of subnet netuids to collect.
        cycle_id: Current cycle identifier.
        semaphore: Concurrency limiter.
        circuit_breaker: Trips after consecutive failures.
        context: Lambda context for timeout checking.

    Returns:
        Dict mapping netuid → snapshot_data (or None on failure).
    """
    results: dict[int, Optional[dict]] = {}

    async def _collect_one(netuid: int) -> None:
        # Check graceful shutdown
        if not _has_time_remaining(context):
            results[netuid] = None
            return

        # Check circuit breaker
        if not circuit_breaker.should_attempt():
            logger.warning(f"Circuit breaker open — skipping netuid={netuid}")
            results[netuid] = None
            return

        async with semaphore:
            try:
                snapshot = await _collect_metagraph(netuid, cycle_id)
                if snapshot is not None:
                    circuit_breaker.record_success()
                    results[netuid] = snapshot
                else:
                    circuit_breaker.record_failure()
                    results[netuid] = None
            except Exception as e:
                circuit_breaker.record_failure(e)
                results[netuid] = None

    tasks = [asyncio.create_task(_collect_one(n)) for n in netuids]
    await asyncio.gather(*tasks, return_exceptions=True)

    return results


async def _collect_metagraph(netuid: int, cycle_id: str) -> Optional[dict]:
    """Collect and validate a single subnet's metagraph.

    Args:
        netuid: Subnet network UID.
        cycle_id: Current cycle identifier (date string).

    Returns:
        Validated snapshot dict ready for storage, or None on failure.
    """
    with instrument("collector", "collect_metagraph", netuid=netuid) as ctx:
        async with AsyncSubtensor() as sub:
            mg = await with_timeout(
                sub.metagraph(netuid=netuid),
                timeout_seconds=DEFAULT_METAGRAPH_TIMEOUT_SECONDS,
                operation_name=f"metagraph(netuid={netuid})",
            )

        # Build snapshot data structure
        neurons = []
        for i in range(mg.n):
            neurons.append({
                "uid": i,
                "hotkey": mg.hotkeys[i],
                "coldkey": mg.coldkeys[i],
                "stake": float(mg.S[i]),
                "incentive": float(mg.I[i]),
                "emission": float(mg.E[i]),
                "consensus": float(mg.C[i]),
                "dividends": float(mg.D[i]),
                "trust": float(mg.Tv[i]),
                "active": bool(mg.active[i]),
                "alpha_stake": float(mg.AS[i]),
                "tao_stake": float(mg.TS[i]),
                "block_at_registration": int(mg.block_at_registration[i]),
            })

        snapshot_data = {
            "metadata": {
                "netuid": netuid,
                "cycle_id": cycle_id,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "source_block_number": int(mg.block_at_registration[0]) if mg.n > 0 else 0,
                "neuron_count": mg.n,
                "blocks_since_last_step": int(mg.blocks_since_last_step),
            },
            "data": {
                "neurons": neurons,
            },
        }

        # Validate before storing
        is_valid, errors = validate_metagraph(snapshot_data)
        if not is_valid:
            ctx["validation_errors"] = errors
            logger.warning(
                f"Metagraph validation failed for netuid={netuid}: {errors}"
            )
            return None

        # Store raw snapshot
        path = _storage.get_date_path("raw/metagraph", cycle_id, netuid)
        _storage.store_snapshot(path, snapshot_data)

        ctx["neuron_count"] = mg.n
        ctx["data_size_bytes"] = len(json.dumps(snapshot_data, default=str))

        return snapshot_data


# ---------------------------------------------------------------------------
# Supplementary data collection
# ---------------------------------------------------------------------------


async def _collect_supplementary_data(
    netuids: list[int],
    cycle_id: str,
    context: Any,
) -> None:
    """Collect registration costs, hyperparameters, alpha prices, and TAO price.

    Each collection is independent — failures in one don't block others.

    Args:
        netuids: Successfully collected subnet netuids.
        cycle_id: Current cycle identifier.
        context: Lambda context for timeout checking.
    """
    # Collect in parallel where possible
    tasks = []

    if _has_time_remaining(context):
        tasks.append(asyncio.create_task(
            _collect_registration_costs(netuids, cycle_id)
        ))

    if _has_time_remaining(context):
        tasks.append(asyncio.create_task(
            _collect_hyperparameters(netuids, cycle_id)
        ))

    if _has_time_remaining(context):
        tasks.append(asyncio.create_task(
            _collect_alpha_prices(netuids, cycle_id)
        ))

    if _has_time_remaining(context):
        tasks.append(asyncio.create_task(
            _collect_tao_price(cycle_id)
        ))

    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)


async def _collect_registration_costs(netuids: list[int], cycle_id: str) -> None:
    """Collect registration costs (burn) for all subnets.

    Registration costs are in RAO on-chain — stored as RAO, converted to TAO
    during processing.
    """
    with instrument("collector", "collect_registration_costs") as ctx:
        costs: list[dict] = []

        async with AsyncSubtensor() as sub:
            for netuid in netuids:
                try:
                    burn_rao = await with_timeout(
                        sub.substrate.query(
                            module="SubtensorModule",
                            storage_function="Burn",
                            params=[netuid],
                        ),
                        timeout_seconds=DEFAULT_QUERY_TIMEOUT_SECONDS,
                        operation_name=f"query_burn(netuid={netuid})",
                    )
                    costs.append({
                        "netuid": netuid,
                        "registration_cost_rao": int(burn_rao),
                        "registration_cost_tao": int(burn_rao) / 1e9,
                    })
                except Exception as e:
                    logger.warning(f"Failed to get burn for netuid={netuid}: {e}")

        if not costs:
            return

        cost_data = {
            "metadata": {
                "cycle_id": cycle_id,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "subnet_count": len(costs),
            },
            "data": {"costs": costs},
        }

        # Validate
        is_valid, errors = validate_registration_cost(cost_data)
        if not is_valid:
            logger.warning(f"Registration cost validation failed: {errors}")

        # Store regardless (partial data is better than none)
        path = _storage.get_date_path("raw/registration-costs", cycle_id)
        _storage.store_snapshot(path, cost_data)
        ctx["subnets_collected"] = len(costs)


async def _collect_hyperparameters(netuids: list[int], cycle_id: str) -> None:
    """Collect hyperparameters for all subnets."""
    with instrument("collector", "collect_hyperparameters") as ctx:
        collected = 0

        async with AsyncSubtensor() as sub:
            for netuid in netuids:
                try:
                    hyperparams = await with_timeout(
                        sub.get_subnet_hyperparameters(netuid=netuid),
                        timeout_seconds=DEFAULT_QUERY_TIMEOUT_SECONDS,
                        operation_name=f"get_hyperparameters(netuid={netuid})",
                    )

                    # Convert hyperparams object to dict
                    hp_dict = {
                        attr: getattr(hyperparams, attr)
                        for attr in dir(hyperparams)
                        if not attr.startswith("_") and not callable(getattr(hyperparams, attr))
                    }

                    hp_data = {
                        "metadata": {
                            "netuid": netuid,
                            "cycle_id": cycle_id,
                            "collected_at": datetime.now(timezone.utc).isoformat(),
                        },
                        "data": hp_dict,
                    }

                    path = _storage.get_date_path("raw/hyperparameters", cycle_id, netuid)
                    _storage.store_snapshot(path, hp_data)
                    collected += 1

                except Exception as e:
                    logger.warning(f"Failed to get hyperparameters for netuid={netuid}: {e}")

        ctx["subnets_collected"] = collected


async def _collect_alpha_prices(netuids: list[int], cycle_id: str) -> None:
    """Collect alpha token prices and pool liquidity for all subnets."""
    with instrument("collector", "collect_alpha_prices") as ctx:
        prices: list[dict] = []

        async with AsyncSubtensor() as sub:
            for netuid in netuids:
                try:
                    # Get alpha/TAO price
                    alpha_price = await with_timeout(
                        sub.get_subnet_price(netuid=netuid),
                        timeout_seconds=DEFAULT_QUERY_TIMEOUT_SECONDS,
                        operation_name=f"get_subnet_price(netuid={netuid})",
                    )

                    # Get pool TAO liquidity
                    pool_tao_rao = await with_timeout(
                        sub.substrate.query(
                            module="SubtensorModule",
                            storage_function="SubnetTAO",
                            params=[netuid],
                        ),
                        timeout_seconds=DEFAULT_QUERY_TIMEOUT_SECONDS,
                        operation_name=f"query_subnet_tao(netuid={netuid})",
                    )

                    # Get pool alpha liquidity
                    pool_alpha_rao = await with_timeout(
                        sub.substrate.query(
                            module="SubtensorModule",
                            storage_function="SubnetAlphaIn",
                            params=[netuid],
                        ),
                        timeout_seconds=DEFAULT_QUERY_TIMEOUT_SECONDS,
                        operation_name=f"query_subnet_alpha(netuid={netuid})",
                    )

                    prices.append({
                        "netuid": netuid,
                        "alpha_tao_price": float(alpha_price),
                        "pool_tao_liquidity": int(pool_tao_rao) / 1e9,
                        "pool_alpha_liquidity": int(pool_alpha_rao) / 1e9,
                    })

                except Exception as e:
                    logger.warning(f"Failed to get alpha price for netuid={netuid}: {e}")

        if not prices:
            return

        price_data = {
            "metadata": {
                "cycle_id": cycle_id,
                "collected_at": datetime.now(timezone.utc).isoformat(),
                "subnet_count": len(prices),
            },
            "data": {"prices": prices},
        }

        # Validate
        is_valid, errors = validate_alpha_prices(price_data)
        if not is_valid:
            logger.warning(f"Alpha price validation failed: {errors}")

        path = _storage.get_date_path("raw/alpha-prices", cycle_id)
        _storage.store_snapshot(path, price_data)
        ctx["subnets_collected"] = len(prices)


async def _collect_tao_price(cycle_id: str) -> None:
    """Collect TAO/USD price from CoinGecko API."""
    with instrument("collector", "collect_tao_price") as ctx:
        url = "https://api.coingecko.com/api/v3/simple/price"
        params: dict[str, str] = {"ids": "bittensor", "vs_currencies": "usd"}
        headers: dict[str, str] = {}

        if _coingecko_api_key:
            headers["x-cg-demo-api-key"] = _coingecko_api_key

        try:
            response = await asyncio.to_thread(
                requests.get,
                url,
                params=params,
                headers=headers,
                timeout=DEFAULT_PRICE_API_TIMEOUT_SECONDS,
            )
            response.raise_for_status()
            data = response.json()

            tao_usd = data.get("bittensor", {}).get("usd")
            if tao_usd is None:
                logger.warning("CoinGecko response missing TAO/USD price")
                return

            price_data = {
                "metadata": {
                    "cycle_id": cycle_id,
                    "collected_at": datetime.now(timezone.utc).isoformat(),
                    "source": "coingecko",
                },
                "data": {
                    "tao_usd": float(tao_usd),
                },
            }

            path = _storage.get_date_path("raw/tao-price", cycle_id)
            _storage.store_snapshot(path, price_data)
            ctx["tao_usd"] = tao_usd

        except Exception as e:
            logger.warning(f"Failed to fetch TAO/USD price: {type(e).__name__}: {e}")


# ---------------------------------------------------------------------------
# SQS publishing
# ---------------------------------------------------------------------------


async def _publish_processing_messages(
    netuids: list[int],
    cycle_id: str,
    trace_id: str,
) -> int:
    """Publish one SQS message per successfully collected subnet.

    Args:
        netuids: List of successfully collected subnet netuids.
        cycle_id: Current cycle identifier.
        trace_id: Trace ID for distributed tracing.

    Returns:
        Number of messages successfully published.
    """
    if not _config.queue.process_queue_url:
        logger.info("No process queue URL configured — skipping SQS publish")
        return 0

    published = 0

    with instrument("collector", "publish_processing_messages") as ctx:
        for netuid in netuids:
            message = {
                "netuid": netuid,
                "date": cycle_id,
                "cycle_id": cycle_id,
                "trace_id": trace_id,
            }

            try:
                await asyncio.to_thread(
                    _sqs_client.send_message,
                    QueueUrl=_config.queue.process_queue_url,
                    MessageBody=json.dumps(message),
                    MessageGroupId=f"subnet-{netuid}",
                )
                published += 1
            except Exception as e:
                logger.error(
                    f"Failed to publish SQS message for netuid={netuid}: "
                    f"{type(e).__name__}: {str(e)[:200]}"
                )

        ctx["messages_published"] = published
        ctx["messages_total"] = len(netuids)

    return published


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------


def _has_time_remaining(context: Any) -> bool:
    """Check if enough Lambda execution time remains for more work.

    Args:
        context: Lambda context object (or None for local testing).

    Returns:
        True if more than GRACEFUL_SHUTDOWN_THRESHOLD_MS remains.
    """
    if context is None:
        return True

    try:
        remaining_ms = context.get_remaining_time_in_millis()
        return remaining_ms > GRACEFUL_SHUTDOWN_THRESHOLD_MS
    except (AttributeError, TypeError):
        # Context doesn't have the method (e.g., in tests)
        return True
