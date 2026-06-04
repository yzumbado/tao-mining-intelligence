#!/usr/bin/env python3
"""Deviation history drift detector.

Reads data/validation_history.jsonl and flags:
1. Any metric with monotonically increasing deviation for 5+ consecutive runs
2. Any metric where avg deviation in last 7 runs exceeds 50% of threshold

Usage:
    python scripts/check_drift.py
"""

import json
import sys
from collections import defaultdict
from pathlib import Path

HISTORY_FILE = Path("data/validation_history.jsonl")

THRESHOLDS = {
    "alpha_price": 2.0,
    "net_tao_yield": 30.0,
    "real_apy_percent": 40.0,
    "competitive_density": 30.0,
}

MONOTONIC_WINDOW = 5
AVG_WINDOW = 7
AVG_THRESHOLD_RATIO = 0.50  # warn if avg > 50% of fail threshold


def load_history() -> list[dict]:
    """Load validation history entries."""
    if not HISTORY_FILE.exists():
        return []
    entries = []
    for line in HISTORY_FILE.read_text().strip().split("\n"):
        if line:
            entries.append(json.loads(line))
    return entries


def check_monotonic_increase(deviations: list[float], window: int) -> bool:
    """True if last `window` values are strictly increasing."""
    if len(deviations) < window:
        return False
    recent = deviations[-window:]
    return all(recent[i] < recent[i + 1] for i in range(len(recent) - 1))


def main():
    entries = load_history()
    if not entries:
        print("No validation history found. Run validate_all_metrics.py first.")
        sys.exit(0)

    print(f"=== Drift Detection ({len(entries)} runs) ===\n")

    # Group deviations by (netuid, metric)
    series: dict[tuple[int, str], list[float]] = defaultdict(list)
    for entry in entries:
        for result in entry.get("results", []):
            key = (result["netuid"], result["metric"])
            series[key].append(result["deviation_pct"])

    warnings = []

    for (netuid, metric), deviations in sorted(series.items()):
        threshold = THRESHOLDS.get(metric, 100.0)

        # Check 1: Monotonically increasing deviation
        if check_monotonic_increase(deviations, MONOTONIC_WINDOW):
            recent = deviations[-MONOTONIC_WINDOW:]
            warnings.append(
                f"📈 SN{netuid}.{metric} trending up: "
                f"{' → '.join(f'{d:.1f}%' for d in recent)} "
                f"(threshold: {threshold}%)"
            )

        # Check 2: Average deviation in recent window > 50% of threshold
        if len(deviations) >= AVG_WINDOW:
            avg = sum(deviations[-AVG_WINDOW:]) / AVG_WINDOW
            limit = threshold * AVG_THRESHOLD_RATIO
            if avg > limit:
                warnings.append(
                    f"📊 SN{netuid}.{metric} avg deviation {avg:.1f}% "
                    f"exceeds {AVG_THRESHOLD_RATIO*100:.0f}% of threshold "
                    f"({limit:.1f}%) over last {AVG_WINDOW} runs"
                )

    if warnings:
        print(f"⚠️  {len(warnings)} drift warnings:\n")
        for w in warnings:
            print(f"   {w}")
        print("\n   Action: Investigate formula divergence before next deploy")
        sys.exit(1)
    else:
        print("✅ No drift detected")
        sys.exit(0)


if __name__ == "__main__":
    main()
