"""Cross-provider metrics validation gate.

Queries live chain for reference subnets, fetches our live rankings output,
and asserts each metric matches within tolerance.

MUST pass before every deploy. Run with:
    source .venv/bin/activate
    python scripts/validate_all_metrics.py

Exit code 0 = all pass, 1 = failures found.

Architecture:
1. RPC fast pre-check (~2s): alpha_price via raw Substrate RPC.
   If price deviates >5%, fail immediately — no point pulling metagraphs.
2. Full validation (~30s): metagraph-based checks for yield, APY, density.

NOTE on APY check: This compares our output against our OWN formula
(MetricsEngine.compute_real_apy) applied to fresh chain data. It is a
FRESHNESS check (catches stale pipeline data), NOT a cross-formula check.
The formula itself was validated against taostats methodology in session
2026-06-03 (see scripts/archive/validate_formulas.py).
"""

import asyncio
import json
import struct
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, "lambda")
from src.processor.metrics import MetricsEngine

HISTORY_FILE = Path("data/validation_history.jsonl")

REFERENCE_SUBNETS = [44, 1, 11, 9, 64]
RANKINGS_URL = "https://dkfh19zkgqq18.cloudfront.net/data/rankings.json"
RPC_ENDPOINT = "https://entrypoint-finney.opentensor.ai"

# Tolerances (percent deviation allowed)
TOLERANCE = {
    "alpha_price": 2.0,
    "net_tao_yield": 30.0,
    "real_apy_percent": 40.0,
    "competitive_density": 30.0,
}

FAST_CHECK_PRICE_TOLERANCE = 5.0  # fail fast if price off by >5%


def _rpc_call(method: str, params: list = None) -> dict:
    """Raw Substrate JSON-RPC call (independent of SDK)."""
    payload = json.dumps({
        "jsonrpc": "2.0", "id": 1,
        "method": method, "params": params or []
    }).encode()
    req = urllib.request.Request(
        RPC_ENDPOINT, data=payload,
        headers={"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=15) as resp:
        return json.loads(resp.read())


def _rpc_alpha_price(netuid: int) -> float | None:
    """Get alpha price via SwapRuntimeApi (no SDK needed)."""
    params_hex = struct.pack("<H", netuid).hex()
    result = _rpc_call("state_call", ["SwapRuntimeApi_current_alpha_price", "0x" + params_hex])
    raw = result.get("result")
    if not raw or raw == "0x":
        return None
    data = bytes.fromhex(raw[2:])
    return int.from_bytes(data[:8], "little") / 1e9 if len(data) >= 8 else None


def _fast_pre_check(our_data: dict) -> bool:
    """RPC price check (~2s). Returns False if obvious failure detected."""
    print("--- Fast pre-check (RPC price) ---")
    for netuid in [44, 1, 64]:
        try:
            rpc_price = _rpc_alpha_price(netuid)
            our_price = our_data.get(netuid, {}).get("alpha_price", 0)
            if rpc_price and our_price > 0:
                delta = abs(rpc_price - our_price) / our_price * 100
                status = "✅" if delta <= FAST_CHECK_PRICE_TOLERANCE else "🔴"
                print(f"  SN{netuid} price: RPC={rpc_price:.6f} Ours={our_price:.6f} Δ={delta:.1f}% {status}")
                if delta > FAST_CHECK_PRICE_TOLERANCE:
                    print(f"\n🔴 FAST FAIL: SN{netuid} price deviation {delta:.1f}% > {FAST_CHECK_PRICE_TOLERANCE}%")
                    print("   Pipeline data is significantly stale. Skipping expensive metagraph checks.")
                    return False
        except Exception as e:
            print(f"  SN{netuid} price: RPC error ({e}) — skipping fast check")
            return True  # can't fast-check, proceed to full validation
    print("  Pre-check passed ✅")
    print()
    return True


async def main():
    import bittensor

    # Fetch our live output
    with urllib.request.urlopen(RANKINGS_URL) as resp:
        our_data = {r["netuid"]: r for r in json.loads(resp.read())}

    # Fast pre-check: RPC price validation (~2s)
    # If price is way off, skip expensive metagraph pulls
    if not _fast_pre_check(our_data):
        _append_history([], ["FAST_FAIL: price deviation > 5%"])
        sys.exit(1)

    failures = []
    all_results = []

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

                all_results.append({
                    "netuid": netuid,
                    "metric": metric,
                    "expected": round(exp_val, 6),
                    "actual": round(our_val, 6),
                    "deviation_pct": round(delta, 2),
                })

                print(
                    f"{netuid:>4} {metric:<22} {exp_val:>12.4f} {our_val:>12.4f} "
                    f"{delta:>5.1f}% {status}"
                )

            print("-" * 68)

    # Append to history
    _append_history(all_results, failures)

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


def _append_history(results: list[dict], failures: list[str]):
    """Append validation run to JSONL history file."""
    HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    entry = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "pass": len(failures) == 0,
        "failures": failures,
    }
    with open(HISTORY_FILE, "a") as f:
        f.write(json.dumps(entry) + "\n")


if __name__ == "__main__":
    asyncio.run(main())
