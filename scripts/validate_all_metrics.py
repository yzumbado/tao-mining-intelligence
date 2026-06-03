"""Cross-provider metrics validation gate.

Queries live chain for reference subnets, fetches our live rankings output,
and asserts each metric matches within tolerance.

MUST pass before every deploy. Run with:
    source .venv/bin/activate
    python scripts/validate_all_metrics.py

Exit code 0 = all pass, 1 = failures found.
"""

import asyncio
import json
import sys
import urllib.request

sys.path.insert(0, "lambda")
from src.processor.metrics import MetricsEngine

REFERENCE_SUBNETS = [44, 1, 11, 9, 64]
RANKINGS_URL = "https://dkfh19zkgqq18.cloudfront.net/data/rankings.json"

# Tolerances (percent deviation allowed)
TOLERANCE = {
    "alpha_price": 2.0,
    "net_tao_yield": 30.0,
    "real_apy_percent": 40.0,
    "competitive_density": 30.0,
}


async def main():
    import bittensor

    # Fetch our live output
    with urllib.request.urlopen(RANKINGS_URL) as resp:
        our_data = {r["netuid"]: r for r in json.loads(resp.read())}

    failures = []

    async with bittensor.AsyncSubtensor() as sub:
        print(f"{'SN':>4} {'Metric':<22} {'Chain':>12} {'Ours':>12} {'Δ%':>6} {'Result'}")
        print("-" * 68)

        for netuid in REFERENCE_SUBNETS:
            mg = await sub.metagraph(netuid)
            hyper = await sub.get_subnet_hyperparameters(netuid)
            price = float(await sub.get_subnet_price(netuid))
            tempo = hyper.tempo
            tpd = 7200.0 / tempo
            n = int(mg.n)

            try:
                pool_raw = await sub.substrate.query(
                    "SubtensorModule", "SubnetTAO", [netuid]
                )
                pool_tao = float(pool_raw) / 1e9 if pool_raw else 0.0
            except Exception:
                pool_tao = 0.0

            validators = [i for i in range(n) if float(mg.D[i]) > 0]
            earning_miners = [
                i for i in range(n)
                if float(mg.I[i]) > 0 and float(mg.E[i]) > 0
            ]

            # Expected values
            val_em = sum(float(mg.E[i]) * tpd for i in validators)
            miner_em = [float(mg.E[i]) * tpd for i in earning_miners]
            avg_m = sum(miner_em) / len(miner_em) if miner_em else 0

            expected = {
                "alpha_price": price,
                "net_tao_yield": avg_m * price,
                "real_apy_percent": MetricsEngine.compute_real_apy(val_em, pool_tao, price),
                "competitive_density": len(earning_miners) / n if n > 0 else 0,
            }

            ours = our_data.get(netuid, {})

            for metric, exp_val in expected.items():
                our_val = ours.get(metric, 0)
                if exp_val == 0 and our_val == 0:
                    delta = 0
                elif exp_val == 0:
                    delta = 100
                else:
                    delta = abs(exp_val - our_val) / abs(exp_val) * 100

                tol = TOLERANCE[metric]
                passed = delta <= tol
                status = "✅" if passed else "🔴 FAIL"
                if not passed:
                    failures.append(f"SN{netuid} {metric}: {delta:.1f}% > {tol}%")

                print(
                    f"{netuid:>4} {metric:<22} {exp_val:>12.4f} {our_val:>12.4f} "
                    f"{delta:>5.1f}% {status}"
                )

            print("-" * 68)

    print()
    if failures:
        print(f"❌ {len(failures)} FAILURES:")
        for f in failures:
            print(f"   {f}")
        print("\nDo NOT deploy until these are resolved.")
        sys.exit(1)
    else:
        print("✅ ALL METRICS PASS — safe to deploy.")
        sys.exit(0)


if __name__ == "__main__":
    asyncio.run(main())
