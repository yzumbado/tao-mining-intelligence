"""Compute realized TAO returns for all subnets with Market Observer history.

Usage: PYTHONPATH=lambda python scripts/compute_realized_returns.py
Requires: AWS profile 'tao', internet access for rankings.json
"""

import json
import urllib.request
import boto3
from src.strategizer.realized_return import compute_realized_tao_return


def main():
    # Load current rankings for alpha APY
    with urllib.request.urlopen("https://dkfh19zkgqq18.cloudfront.net/data/rankings.json") as r:
        rankings = json.loads(r.read())
    apy_by_netuid = {r["netuid"]: r["real_apy_percent"] for r in rankings}

    # Query DynamoDB for all subnets with history
    session = boto3.Session(profile_name="tao", region_name="us-east-1")
    ddb = session.resource("dynamodb")
    table = ddb.Table("tao-pipeline")

    results = []
    for netuid in sorted(apy_by_netuid.keys()):
        # Query history for this subnet
        resp = table.query(
            KeyConditionExpression="PK = :pk",
            ExpressionAttributeValues={":pk": f"HISTORY#{netuid}"},
            ScanIndexForward=True,  # oldest first
        )
        items = resp.get("Items", [])
        if len(items) < 10:  # Need at least ~2 hours of data
            continue

        # Convert to format expected by compute function
        history = [
            {"timestamp": item["SK"], "alpha_price": str(item["alpha_price"]),
             "pool_tao": str(item.get("pool_tao", 0))}
            for item in items
        ]

        apy = apy_by_netuid.get(netuid, 0)
        result = compute_realized_tao_return(history, apy)
        if result:
            result["netuid"] = netuid
            result["alpha_apy"] = apy
            results.append(result)

    # Sort by realized return
    results.sort(key=lambda x: x["realized_annualized_tao_return_pct"], reverse=True)

    # Print report
    print(f"{'SN':>4} {'αAPY%':>7} {'TAO ret%':>8} {'α∆%':>7} {'pool∆%':>7} {'days':>5} {'conf':>6} {'> Root':>6}")
    print("-" * 65)
    for r in results[:30]:
        flag = "✅" if r["beats_root"] else "❌"
        print(f"{r['netuid']:>4} {r['alpha_apy']:>7.0f} {r['realized_annualized_tao_return_pct']:>8.0f} "
              f"{r['alpha_price_change_pct']:>+7.1f} {r['pool_tao_change_pct']:>+7.1f} "
              f"{r['data_days']:>5.1f} {r['confidence']:>6} {flag:>6}")

    print(f"\n{'='*65}")
    beats = sum(1 for r in results if r["beats_root"])
    print(f"{beats}/{len(results)} subnets beat Root (3.1% APY) over available data period")
    print(f"⚠️  Only {results[0]['data_days']:.0f} days of data — LOW confidence")
    print(f"\nTop 5 by realized TAO return:")
    for r in results[:5]:
        print(f"  SN{r['netuid']:>3}: {r['realized_annualized_tao_return_pct']:.0f}% TAO "
              f"(alpha price {r['alpha_price_change_pct']:+.1f}%, pool {r['pool_tao_change_pct']:+.1f}%)")


if __name__ == "__main__":
    main()
