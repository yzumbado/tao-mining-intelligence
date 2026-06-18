#!/usr/bin/env python3
"""TAO Staking Strategy Advisor — on-demand portfolio analysis.

Reads live rankings from CloudFront and your position config,
produces actionable recommendations.

Usage:
    python scripts/strategy.py
    python scripts/strategy.py --profile aggressive
"""

import argparse
import json
import sys
import urllib.request
from dataclasses import dataclass

RANKINGS_URL = "https://dkfh19zkgqq18.cloudfront.net/data/rankings.json"

# --- Your Position Config ---
# Edit this to match your current staking positions.
MY_POSITIONS = {
    "root": 56.96,        # TAO in root network
    "subnets": {
        34: {"staked_tao": 0},  # Approximate TAO equivalent staked
        64: {"staked_tao": 0},
        19: {"staked_tao": 0},
        44: {"staked_tao": 0},
    },
}

# --- Risk Profiles ---
PROFILES = {
    "conservative": {
        "max_concentration_risk": 0.2,
        "min_pool_tao": 20000,
        "max_self_mining_risk": 0.0,
        "min_earning_miners": 5,
        "allowed_models": ["TIERED", "PROPORTIONAL"],
        "max_trend_decline": -0.03,  # Won't enter if alpha down >3%/week
    },
    "moderate": {
        "max_concentration_risk": 0.4,
        "min_pool_tao": 10000,
        "max_self_mining_risk": 0.3,
        "min_earning_miners": 1,
        "allowed_models": ["TIERED", "PROPORTIONAL", "WINNER_TAKES_ALL"],
        "max_trend_decline": -0.08,
    },
    "aggressive": {
        "max_concentration_risk": 0.7,
        "min_pool_tao": 3000,
        "max_self_mining_risk": 0.5,
        "min_earning_miners": 0,
        "allowed_models": ["TIERED", "PROPORTIONAL", "WINNER_TAKES_ALL", "UNKNOWN"],
        "max_trend_decline": -0.15,
    },
}


@dataclass
class Recommendation:
    action: str         # HOLD, EXIT, ENTER, MOVE
    netuid: int
    reason: str
    urgency: str        # high, medium, low
    apy: float
    trend: float


def load_rankings() -> list[dict]:
    with urllib.request.urlopen(RANKINGS_URL) as r:
        return json.loads(r.read())


def analyze_position(netuid: int, r: dict, profile: dict) -> Recommendation:
    """Analyze a single position against the risk profile."""
    issues = []

    # Trend check — is alpha eroding your yield?
    if r["price_trend_7d"] < profile["max_trend_decline"]:
        issues.append(f"alpha depreciating {r['price_trend_7d']*100:.1f}%/week (threshold: {profile['max_trend_decline']*100:.0f}%)")

    # Concentration risk
    conc = r.get("concentration_risk", {}).get("risk", 0)
    if conc > profile["max_concentration_risk"]:
        issues.append(f"concentration risk {conc:.1f} exceeds limit {profile['max_concentration_risk']}")

    # Self-mining
    if r["self_mining_risk"] > profile["max_self_mining_risk"]:
        issues.append(f"self-mining risk {r['self_mining_risk']:.1f}")

    # Below median APY
    if r["real_apy_percent"] < 50:
        issues.append(f"APY {r['real_apy_percent']:.0f}% below 50% floor")

    if issues:
        urgency = "high" if r["price_trend_7d"] < -0.05 else "medium"
        return Recommendation(
            action="EXIT",
            netuid=netuid,
            reason="; ".join(issues),
            urgency=urgency,
            apy=r["real_apy_percent"],
            trend=r["price_trend_7d"],
        )

    return Recommendation(
        action="HOLD",
        netuid=netuid,
        reason="position meets all criteria",
        urgency="low",
        apy=r["real_apy_percent"],
        trend=r["price_trend_7d"],
    )


def find_opportunities(rankings: list[dict], profile: dict, my_netuids: set) -> list[dict]:
    """Find subnets that pass the risk profile and you're not already in."""
    candidates = []
    for r in rankings:
        if r["netuid"] in my_netuids or r["netuid"] == 0:
            continue
        # Apply filters
        if r.get("liquidity_warning") and r["pool_tao_liquidity"] < profile["min_pool_tao"]:
            continue
        if r["pool_tao_liquidity"] < profile["min_pool_tao"]:
            continue
        if r["self_mining_risk"] > profile["max_self_mining_risk"]:
            continue
        if r.get("concentration_risk", {}).get("risk", 0) > profile["max_concentration_risk"]:
            continue
        if r["earning_miners_count"] < profile["min_earning_miners"]:
            continue
        if r["reward_model"] not in profile["allowed_models"]:
            continue
        if r["price_trend_7d"] < profile["max_trend_decline"]:
            continue
        candidates.append(r)
    return candidates[:10]


def main():
    parser = argparse.ArgumentParser(description="TAO Staking Strategy Advisor")
    parser.add_argument("--profile", default="moderate", choices=PROFILES.keys())
    args = parser.parse_args()

    profile = PROFILES[args.profile]
    rankings = load_rankings()
    rankings_map = {r["netuid"]: r for r in rankings}
    my_netuids = set(MY_POSITIONS["subnets"].keys())

    print(f"{'='*60}")
    print(f"  TAO STRATEGY ADVISOR — {args.profile.upper()} profile")
    print(f"{'='*60}")
    print()

    # Analyze current positions
    print("📊 CURRENT POSITIONS")
    print(f"   Root: {MY_POSITIONS['root']:.2f} τ")
    print()

    exit_candidates = []
    for netuid in sorted(my_netuids):
        r = rankings_map.get(netuid)
        if not r:
            print(f"   SN{netuid}: ⚠️  NOT IN RANKINGS (may be deregistered)")
            continue
        rec = analyze_position(netuid, r, profile)
        rank = next((i+1 for i, x in enumerate(rankings) if x["netuid"] == netuid), "?")

        icon = "✅" if rec.action == "HOLD" else "⚠️"
        print(f"   {icon} SN{netuid} (#{rank}) | APY: {rec.apy:.0f}% | Trend: {rec.trend*100:+.1f}%")
        if rec.action != "HOLD":
            print(f"      → {rec.action}: {rec.reason}")
            print(f"      Urgency: {rec.urgency}")
            exit_candidates.append(rec)
        print()

    # Find opportunities
    print("🎯 TOP OPPORTUNITIES (pass your risk filters)")
    print()
    opportunities = find_opportunities(rankings, profile, my_netuids)
    if not opportunities:
        print("   No subnets pass all filters. Consider relaxing profile.")
    else:
        for r in opportunities[:5]:
            rank = next((i+1 for i, x in enumerate(rankings) if x["netuid"] == r["netuid"]), "?")
            trend_icon = "↑" if r["trend_direction"] == "up" else "↓" if r["trend_direction"] == "down" else "→"
            print(f"   SN{r['netuid']} (#{rank}) | APY: {r['real_apy_percent']:.0f}% | "
                  f"{trend_icon}{r['price_trend_7d']*100:+.1f}% | Pool: {r['pool_tao_liquidity']/1000:.0f}K | "
                  f"{r['reward_model']}")
        print()

    # Generate recommendations
    if exit_candidates or opportunities:
        print("💡 RECOMMENDATIONS")
        print()
        for rec in exit_candidates:
            if opportunities:
                best = opportunities[0]
                print(f"   MOVE SN{rec.netuid} → SN{best['netuid']}")
                print(f"   Reason: {rec.reason}")
                print(f"   Gain: {rec.apy:.0f}% → {best['real_apy_percent']:.0f}% APY")
                print()
        if not exit_candidates and opportunities:
            print(f"   All positions healthy. If adding new capital, consider SN{opportunities[0]['netuid']}.")
    else:
        print("💡 HOLD ALL — no action needed.")

    print()
    print(f"{'='*60}")
    print(f"  Data: {len(rankings)} subnets | Network median APY: {sorted([r['real_apy_percent'] for r in rankings])[len(rankings)//2]:.0f}%")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
