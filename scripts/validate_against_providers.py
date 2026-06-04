#!/usr/bin/env python3
"""Cross-provider spot check — validates our output via independent chain RPC.

Uses raw Substrate JSON-RPC runtime API calls (NOT our SDK) as a second code
path to the same chain data. Catches bugs in our SDK wrapper or field interpretation.

This is a SOFT check — warnings only, never blocks deploy.

Usage:
    python scripts/validate_against_providers.py
"""

import json
import struct
import sys
import urllib.request

RANKINGS_URL = "https://dkfh19zkgqq18.cloudfront.net/data/rankings.json"
RPC_ENDPOINT = "https://entrypoint-finney.opentensor.ai"
SPOT_CHECK_SUBNETS = [44, 1, 64]
TOLERANCE_PRICE_PCT = 10.0


def rpc_call(method: str, params: list = None) -> dict:
    """Make a raw Substrate JSON-RPC call."""
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


def get_alpha_price_rpc(netuid: int) -> float | None:
    """Get alpha price via SwapRuntimeApi (independent of our SDK)."""
    params_hex = struct.pack("<H", netuid).hex()
    result = rpc_call("state_call", ["SwapRuntimeApi_current_alpha_price", "0x" + params_hex])
    raw = result.get("result")
    if not raw or raw == "0x":
        return None
    data = bytes.fromhex(raw[2:])
    if len(data) >= 8:
        return int.from_bytes(data[:8], "little") / 1e9
    return None


def get_current_block() -> int:
    """Get current block number from chain."""
    result = rpc_call("chain_getHeader")
    return int(result["result"]["number"], 16)


def main():
    print("=== Provider Spot Check (Raw RPC vs Our Output) ===")
    print(f"Endpoint: {RPC_ENDPOINT}")
    print()

    # Fetch our rankings
    try:
        with urllib.request.urlopen(RANKINGS_URL, timeout=10) as resp:
            our_data = {r["netuid"]: r for r in json.loads(resp.read())}
    except Exception as e:
        print(f"⚠️  Cannot fetch rankings: {e}")
        return

    # Get current block for freshness check
    try:
        chain_block = get_current_block()
        print(f"Chain block: {chain_block}")
    except Exception as e:
        print(f"⚠️  Cannot query chain: {e}")
        return

    warnings = []
    checks_passed = 0
    checks_total = 0

    print(f"\n{'SN':>4} {'Metric':<16} {'RPC':>14} {'Ours':>14} {'Δ%':>8} {'Status'}")
    print("-" * 62)

    for netuid in SPOT_CHECK_SUBNETS:
        ours = our_data.get(netuid)
        if not ours:
            print(f"{netuid:>4} NOT IN RANKINGS")
            warnings.append(f"SN{netuid} missing from rankings")
            continue

        # Alpha price via SwapRuntimeApi (same API the SDK uses, but our own RPC call)
        try:
            rpc_price = get_alpha_price_rpc(netuid)
            our_price = ours.get("alpha_price", 0)
            checks_total += 1

            if rpc_price and our_price > 0:
                deviation = abs(rpc_price - our_price) / our_price * 100
                passed = deviation <= TOLERANCE_PRICE_PCT
                status = "✅" if passed else "⚠️"
                if not passed:
                    warnings.append(f"SN{netuid} alpha_price: {deviation:.1f}% deviation")
                else:
                    checks_passed += 1
                print(f"{netuid:>4} {'alpha_price':<16} {rpc_price:>14.9f} {our_price:>14.9f} {deviation:>7.1f}% {status}")
            elif rpc_price:
                print(f"{netuid:>4} {'alpha_price':<16} {rpc_price:>14.9f} {'0 (ours)':>14} {'N/A':>8} ⚠️")
                warnings.append(f"SN{netuid} our price is 0")
            else:
                print(f"{netuid:>4} {'alpha_price':<16} {'None':>14} {our_price:>14.9f} {'N/A':>8} ⚠️")
        except Exception as e:
            print(f"{netuid:>4} {'alpha_price':<16} {'ERROR':>14} {str(e)[:14]:>14} {'':>8} ⚠️")

    print("-" * 62)
    print(f"\nResults: {checks_passed}/{checks_total} passed")

    if warnings:
        print(f"\n⚠️  Warnings ({len(warnings)}):")
        for w in warnings:
            print(f"   {w}")
    else:
        print("\n✅ All spot checks passed")

    # Always exit 0 — this is advisory only
    sys.exit(0)


if __name__ == "__main__":
    main()
