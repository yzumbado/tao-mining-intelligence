"""Validator Leaderboard — ranks validators per subnet by performance.

Pure functions. No AWS imports.
Answers: "Who should I delegate to on SN44?"
"""

from typing import Optional
import statistics


def compute_validator_leaderboard(
    snapshots: list[dict],
    netuid: int,
) -> list[dict]:
    """Compute validator rankings from historical metagraph snapshots.

    Args:
        snapshots: List of metagraph snapshot dicts (from S3 raw/metagraph/{date}/{netuid}.json),
            sorted oldest→newest. Each has metadata + data.neurons[].
        netuid: Subnet ID (for labeling).

    Returns:
        List of validator dicts sorted by score (best first).
    """
    if not snapshots:
        return []

    # Collect per-validator time series
    validators: dict[str, dict] = {}  # hotkey → accumulated data

    for snap in snapshots:
        neurons = snap.get("data", {}).get("neurons", [])
        date = snap.get("metadata", {}).get("cycle_id", "")

        for n in neurons:
            if not n.get("validator_permit"):
                continue
            if n.get("dividends", 0) <= 0 and n.get("stake", 0) <= 0:
                continue

            hotkey = n["hotkey"]
            if hotkey not in validators:
                validators[hotkey] = {
                    "hotkey": hotkey,
                    "coldkey": n.get("coldkey", ""),
                    "uid": n["uid"],
                    "dividends_history": [],
                    "vtrust_history": [],
                    "active_history": [],
                    "stake_history": [],
                    "delegate_take": n.get("delegate_take"),
                    "dates_seen": 0,
                }

            v = validators[hotkey]
            v["dividends_history"].append(n.get("dividends", 0))
            v["vtrust_history"].append(n.get("validator_trust", 0))
            v["active_history"].append(1 if n.get("active") else 0)
            v["stake_history"].append(n.get("alpha_stake", 0) or n.get("stake", 0))
            v["dates_seen"] += 1
            # Update delegate_take with latest value
            if n.get("delegate_take") is not None:
                v["delegate_take"] = n["delegate_take"]

    if not validators:
        return []

    total_days = len(snapshots)

    # Score each validator
    results = []
    for hotkey, v in validators.items():
        divs = v["dividends_history"]
        vtrusts = v["vtrust_history"]
        actives = v["active_history"]
        stakes = v["stake_history"]

        avg_dividends = statistics.mean(divs) if divs else 0
        avg_vtrust = statistics.mean(vtrusts) if vtrusts else 0
        uptime = sum(actives) / len(actives) if actives else 0
        latest_stake = stakes[-1] if stakes else 0
        total_stake_all = sum(s[-1] for s in (val["stake_history"] for val in validators.values()) if s)
        stake_share = latest_stake / total_stake_all if total_stake_all > 0 else 0

        # Consistency: lower std dev relative to mean = more consistent
        if len(divs) > 1 and avg_dividends > 0:
            cv = statistics.stdev(divs) / avg_dividends  # coefficient of variation
            consistency = max(0.0, 1.0 - min(cv, 2.0) / 2.0)  # 0=chaotic, 1=rock-solid
        else:
            consistency = 0.5

        # Vtrust trend (rising/falling)
        if len(vtrusts) >= 3:
            first_half = statistics.mean(vtrusts[:len(vtrusts)//2])
            second_half = statistics.mean(vtrusts[len(vtrusts)//2:])
            vtrust_trend = second_half - first_half
        else:
            vtrust_trend = 0.0

        # Commission (delegate take)
        take = v["delegate_take"]
        commission_pct = take * 100 if take is not None else None

        # Net yield to delegator (dividends after commission)
        if take is not None:
            effective_yield = avg_dividends * (1.0 - take)
        else:
            effective_yield = avg_dividends * 0.82  # Assume 18% if unknown

        # Composite score: yield × consistency × uptime × (1 - commission_penalty)
        commission_penalty = take if take is not None else 0.18
        score = effective_yield * 1000 * consistency * uptime * (1.0 - commission_penalty * 0.5)

        results.append({
            "hotkey": hotkey,
            "hotkey_short": hotkey[:12] + "...",
            "coldkey_short": v["coldkey"][:12] + "..." if v["coldkey"] else "",
            "uid": v["uid"],
            "netuid": netuid,
            "avg_dividends": round(avg_dividends, 6),
            "effective_yield": round(effective_yield, 6),
            "avg_vtrust": round(avg_vtrust, 4),
            "vtrust_trend": round(vtrust_trend, 4),
            "uptime_pct": round(uptime * 100, 1),
            "consistency": round(consistency, 3),
            "stake": round(latest_stake, 2),
            "stake_share_pct": round(stake_share * 100, 1),
            "commission_pct": round(commission_pct, 1) if commission_pct is not None else None,
            "days_observed": v["dates_seen"],
            "score": round(score, 6),
        })

    results.sort(key=lambda x: x["score"], reverse=True)

    # Assign rank
    for i, r in enumerate(results):
        r["rank"] = i + 1

    return results
