"""Market Observer Lambda — high-frequency cache + time-series writer.

Runs every 10 minutes via EventBridge. For each active subnet:
1. Queries chain via bittensor AsyncSubtensor (same as Collector — proven at scale)
2. Writes latest market data to DynamoDB cache (CACHE#{netuid}|MARKET_DATA)
3. Appends observation to DynamoDB history (HISTORY#{netuid}|{timestamp})

The cache serves other Lambdas needing current price/pool data.
The history enables observed APY calculation (vs single-point extrapolation).
"""

import asyncio
import logging
import time
from datetime import datetime, timezone
from typing import Any, Optional

import boto3

from src.config import get_config, PipelineConfig
from src.state.state_manager import StateManager
from src.instrumentation import instrument

logger = logging.getLogger("tao-pipeline")

_config: Optional[PipelineConfig] = None
_state_manager: Optional[StateManager] = None
_cw_client = None


def _init_clients() -> None:
    global _config, _state_manager, _cw_client
    if _config is not None:
        return
    _config = get_config()
    _state_manager = StateManager(_config)
    if _config.is_aws:
        _cw_client = boto3.client("cloudwatch", region_name=_config.region)


def handle(event: dict, context: Any) -> dict:
    """Lambda entry point. Observes market data for all active subnets."""
    _init_clients()

    with instrument("market_observer", "handle") as ctx:
        active_subnets = _state_manager.get_active_subnets()
        if not active_subnets:
            return {"status": "no_subnets"}

        result = asyncio.run(_observe_all(active_subnets))

        _publish_metric(result["observed"])

        ctx["observed"] = result["observed"]
        ctx["errors"] = result["errors"]
        ctx["block"] = result["block"]

        return result


async def _observe_all(active_subnets: list[int]) -> dict:
    """Query chain for all subnets via persistent websocket connection."""
    from bittensor import AsyncSubtensor

    now = datetime.now(timezone.utc)
    timestamp = now.isoformat()
    ttl_epoch = int(now.timestamp()) + (30 * 86400)

    observed = 0
    errors = 0
    block = 0

    try:
        async with AsyncSubtensor() as sub:
            block = int(await sub.substrate.get_block_number())  # type: ignore

            for netuid in active_subnets:
                try:
                    price = float(await sub.get_subnet_price(netuid))
                    pool_tao_raw = await sub.substrate.query(
                        "SubtensorModule", "SubnetTAO", [netuid])
                    pool_tao = int(pool_tao_raw) / 1e9 if pool_tao_raw else 0.0

                    if price <= 0 or pool_tao <= 0:
                        errors += 1
                        continue

                    pool_alpha = pool_tao / price

                    _state_manager.write_market_cache(netuid, {
                        "alpha_price": price,
                        "pool_tao": pool_tao,
                        "pool_alpha": pool_alpha,
                        "block": block,
                        "cached_at": timestamp,
                    })

                    _state_manager.append_market_history(netuid, timestamp, {
                        "alpha_price": price,
                        "pool_tao": pool_tao,
                        "pool_alpha": pool_alpha,
                        "block": block,
                    }, ttl_epoch)

                    observed += 1

                except Exception as e:
                    logger.warning(f"SN{netuid}: {str(e)[:80]}")
                    errors += 1

    except Exception as e:
        logger.error(f"Chain connection failed: {str(e)[:200]}")

    return {
        "status": "complete",
        "observed": observed,
        "errors": errors,
        "block": block,
    }


def _publish_metric(observed: int) -> None:
    """Publish SubnetsObserved metric for staleness alarming."""
    if not _cw_client:
        return
    try:
        _cw_client.put_metric_data(
            Namespace="TaoPipeline",
            MetricData=[{
                "MetricName": "MarketObserverSubnetsObserved",
                "Value": observed,
                "Unit": "Count",
            }],
        )
    except Exception:
        pass
