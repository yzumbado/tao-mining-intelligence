"""Generate validator leaderboard for a subnet from historical snapshots.

Usage: PYTHONPATH=lambda python scripts/validator_leaderboard.py [netuid]
Default: SN44
"""

import json
import sys
import boto3
from src.strategizer.validator_leaderboard import compute_validator_leaderboard


def main():
    netuid = int(sys.argv[1]) if len(sys.argv) > 1 else 44

    session = boto3.Session(profile_name="tao", region_name="us-east-1")
    s3 = session.client("s3")
    bucket = "tao-intelligence-651484323929"

    # List all dates with metagraph data
    resp = s3.list_objects_v2(Bucket=bucket, Prefix="raw/metagraph/", Delimiter="/")
    dates = sorted(p["Prefix"].split("/")[2] for p in resp.get("CommonPrefixes", []))

    print(f"Loading SN{netuid} snapshots from {len(dates)} days ({dates[0]} → {dates[-1]})...")

    snapshots = []
    for date in dates:
        key = f"raw/metagraph/{date}/{netuid}.json"
        try:
            obj = s3.get_object(Bucket=bucket, Key=key)
            data = json.loads(obj["Body"].read())
            snapshots.append(data)
        except s3.exceptions.NoSuchKey:
            pass

    print(f"Loaded {len(snapshots)} snapshots\n")

    leaderboard = compute_validator_leaderboard(snapshots, netuid)

    if not leaderboard:
        print("No validators found.")
        return

    # Print leaderboard
    print(f"{'═' * 100}")
    print(f"  SN{netuid} Validator Leaderboard ({len(snapshots)}-day history)")
    print(f"{'═' * 100}")
    print(f"{'#':>2} {'Hotkey':>14} {'Score':>8} {'Yield/d':>8} {'VTrust':>7} {'Up%':>5} "
          f"{'Consist':>7} {'Comm%':>6} {'Stake%':>7} {'Days':>4}")
    print(f"{'─' * 100}")

    for v in leaderboard:
        comm = f"{v['commission_pct']:.0f}%" if v['commission_pct'] is not None else "??"
        print(f"{v['rank']:>2} {v['hotkey_short']:>14} {v['score']:>8.4f} "
              f"{v['effective_yield']:>8.5f} {v['avg_vtrust']:>7.3f} {v['uptime_pct']:>5.0f} "
              f"{v['consistency']:>7.3f} {comm:>6} {v['stake_share_pct']:>6.1f}% {v['days_observed']:>4}")

    print(f"\n{'─' * 100}")
    # Recommendation
    top = leaderboard[0]
    print(f"\n  ★ RECOMMEND: Delegate to {top['hotkey_short']}")
    print(f"    Score: {top['score']:.4f} | Commission: {top['commission_pct']}% | "
          f"Uptime: {top['uptime_pct']:.0f}% | VTrust: {top['avg_vtrust']:.3f}")

    # Warnings
    for v in leaderboard:
        if v["vtrust_trend"] < -0.05:
            print(f"  ⚠️  {v['hotkey_short']}: vtrust DECLINING ({v['vtrust_trend']:+.3f})")
        if v["uptime_pct"] < 90:
            print(f"  ⚠️  {v['hotkey_short']}: low uptime ({v['uptime_pct']:.0f}%)")


if __name__ == "__main__":
    main()
