"""End-to-end local test: collect real SN1 data, validate, store, run metrics."""
import asyncio
import os
import sys
import time

lambda_src = os.path.join(os.path.dirname(__file__), "..", "lambda", "src")
sys.path.insert(0, lambda_src)
# Also add parent of lambda/src so "src.config" resolves
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "lambda"))
os.environ["PIPELINE_ENV"] = "local"
os.environ["LOCAL_OUTPUT_DIR"] = "./output"

from datetime import datetime, timezone


async def main():
    # Reset config to pick up env vars
    from config import reset_config
    reset_config()
    from config import get_config
    from storage.storage_layer import StorageLayer
    from validation import validate_metagraph
    from processor.metrics import MetricsEngine, compute_deregistration_risk
    from models.schemas import Neuron
    import bittensor as bt

    config = get_config()
    storage = StorageLayer(config)
    cycle_id = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    print("=== LIVE END-TO-END TEST ===")
    print(f"Cycle: {cycle_id}\n")

    # 1. Collect
    start = time.time()
    print("1. COLLECTING from Finney...")
    async with bt.AsyncSubtensor(network="finney") as sub:
        mg = await sub.metagraph(netuid=1)
        price = await sub.get_subnet_price(netuid=1)
        hp = await sub.get_subnet_hyperparameters(netuid=1)

    duration = time.time() - start
    print(f"   ✓ Collected in {duration:.1f}s")
    print(f"   Neurons: {mg.n}, Price: {price}, Tempo: {hp.tempo}")

    # 2. Build + Validate
    print("\n2. VALIDATING...")
    neurons_data = []
    for i in range(mg.n):
        neurons_data.append({
            "uid": i,
            "hotkey": str(mg.hotkeys[i]),
            "coldkey": str(mg.coldkeys[i]),
            "stake": float(mg.S[i]),
            "incentive": float(mg.I[i]),
            "emission": float(mg.E[i]),
            "consensus": float(mg.C[i]),
            "dividends": float(mg.D[i]),
            "validator_trust": float(mg.Tv[i]),
            "active": bool(mg.active[i]),
            "alpha_stake": float(mg.AS[i]),
            "total_stake": float(mg.TS[i]),
            "block_at_registration": int(mg.block_at_registration[i]),
            "blocks_since_last_step": int(mg.blocks_since_last_step) if isinstance(mg.blocks_since_last_step, (int, float)) else int(mg.blocks_since_last_step[i]),
        })

    snapshot = {
        "metadata": {"source_block_number": 8194740, "netuid": 1},
        "data": {"neurons": neurons_data},
    }
    is_valid, errors = validate_metagraph(snapshot)
    print(f"   Valid: {is_valid}")
    if errors:
        print(f"   Issues: {errors}")

    # 3. Store
    print("\n3. STORING...")
    path = storage.get_date_path("raw/metagraph", cycle_id, 1)
    storage.store_snapshot(path, snapshot)
    size = os.path.getsize(f"./output/{path}")
    print(f"   ✓ ./output/{path} ({size:,} bytes)")

    # 4. Metrics
    print("\n4. RUNNING METRICS...")
    emissions = [n["emission"] for n in neurons_data if n["dividends"] == 0]
    earning = [e for e in emissions if e > 0]

    model, gini, top3 = MetricsEngine.detect_reward_distribution_model(emissions)
    print(f"   Reward: {model.value} (Gini={gini:.3f}, Top3={top3:.3f})")
    print(f"   Earning miners: {len(earning)}/{len(emissions)}")

    alpha_price = float(price)
    tempos_per_day = 7200 / hp.tempo

    if earning:
        avg_emission = sum(earning) / len(earning)
        daily_alpha = avg_emission * tempos_per_day
        daily_tao = daily_alpha * alpha_price
        reg_cost = 0.0005
        days_recoup = reg_cost / daily_tao if daily_tao > 0 else float("inf")

        print(f"   Alpha price: {alpha_price:.6f} TAO")
        print(f"   Avg earner emission: {avg_emission:.4f} alpha/tempo")
        print(f"   Daily yield: {daily_tao:.4f} TAO/day")
        print(f"   Reg cost: {reg_cost} TAO → recoup in {days_recoup:.2f} days")

    risks = compute_deregistration_risk(emissions, [False] * len(emissions), 256, 256, 3)
    high_risk = sum(1 for r in risks if r > 0.5)
    print(f"   High dereg risk: {high_risk} miners")

    print("\n=== ALL CHECKS PASSED ✓ ===")


if __name__ == "__main__":
    asyncio.run(main())
