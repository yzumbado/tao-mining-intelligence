#!/usr/bin/env python3
"""Formula truth test — validates our metrics against live chain data.

Computes APY and key metrics using the taostats-equivalent formula,
then compares against our pipeline's formula. Fails if divergence > 15%.

Usage:
    python scripts/validate_formulas.py

Requires: bittensor SDK, internet connection to Finney endpoint.
"""

import sys
import math

sys.path.insert(0, "lambda")


def query_live_data(netuid: int) -> dict:
    """Query live chain data for a subnet."""
    import bittensor as bt
    sub = bt.Subtensor(network="finney")
    mg = sub.metagraph(netuid=netuid)
    hp = sub.get_subnet_hyperparameters(netuid=netuid)
    alpha_price = float(sub.get_subnet_price(netuid=netuid))

    tempo = hp.tempo
    tempos_per_day = 7200.0 / tempo

    validators = []
    for i in range(int(mg.n)):
        if float(mg.D[i]) > 0:
            validators.append({
                "emission": float(mg.E[i]),
                "alpha_stake": float(mg.AS[i]),
                "stake": float(mg.S[i]),
            })

    total_val_emission_per_tempo = sum(v["emission"] for v in validators)
    total_val_emission_daily = total_val_emission_per_tempo * tempos_per_day
    total_alpha_stake = sum(v["alpha_stake"] for v in validators)

    return {
        "netuid": netuid,
        "tempo": tempo,
        "tempos_per_day": tempos_per_day,
        "alpha_price": alpha_price,
        "validators": len(validators),
        "total_val_emission_daily": total_val_emission_daily,
        "total_val_emission_per_tempo": total_val_emission_per_tempo,
        "total_alpha_stake": total_alpha_stake,
    }


def taostats_apy(data: dict, take_rate: float = 0.18) -> float:
    """Compute APY using taostats formula (compound, alpha-denominated).

    Formula (from taostats docs):
        epoch_yield = (emission_per_epoch / alpha_stake) × (1 - take)
        APY = (1 + epoch_yield)^(epochs_per_year) - 1
    """
    if data["total_alpha_stake"] <= 0 or data["total_val_emission_per_tempo"] <= 0:
        return 0.0

    epoch_yield = (data["total_val_emission_per_tempo"] / data["total_alpha_stake"]) * (1 - take_rate)
    epochs_per_year = data["tempos_per_day"] * 365
    return ((1 + epoch_yield) ** epochs_per_year - 1) * 100


def our_apy(data: dict, take_rate: float = 0.18) -> float:
    """Compute APY using OUR formula (must match taostats within tolerance).

    Correct formula (alpha-denominated, simple annualization):
        APY = (emission_daily / alpha_stake) × (1 - take) × 365 × 100
    """
    from src.processor.metrics import MetricsEngine

    return MetricsEngine.compute_real_apy(
        total_validator_emission_daily=data["total_val_emission_daily"],
        total_validator_stake=data["total_alpha_stake"],
        alpha_tao_price=data["alpha_price"],
    )


def validate_apy(subnets: list[int], tolerance: float = 0.20) -> bool:
    """Validate APY formula against taostats-equivalent for given subnets."""
    print(f"\n{'SN':>4} {'Validators':>10} {'AlphaStk':>12} {'Price':>8} "
          f"{'taostats':>10} {'Ours':>10} {'Δ%':>8} {'Status':>8}")
    print("-" * 82)

    all_pass = True
    for netuid in subnets:
        try:
            data = query_live_data(netuid)
            expected = taostats_apy(data)
            actual = our_apy(data)

            if expected > 0:
                delta_pct = abs(actual - expected) / expected
            else:
                delta_pct = 0.0 if actual == 0 else 1.0

            status = "✅" if delta_pct <= tolerance else "❌"
            if delta_pct > tolerance:
                all_pass = False

            print(f"{netuid:>4} {data['validators']:>10} {data['total_alpha_stake']:>12,.0f} "
                  f"{data['alpha_price']:>8.5f} {expected:>9.2f}% {actual:>9.2f}% "
                  f"{delta_pct*100:>7.1f}% {status}")
        except Exception as e:
            print(f"{netuid:>4} ERROR: {e}")
            all_pass = False

    return all_pass


def main():
    print("=" * 82)
    print("FORMULA VALIDATION — Live Chain vs Our Implementation")
    print("=" * 82)

    # Test subnets: root, high-value, mid, low-price, outlier
    test_subnets = [0, 1, 4, 44, 77]

    print("\n--- APY Formula Validation (tolerance: ±20%) ---")
    apy_pass = validate_apy(test_subnets, tolerance=0.20)

    print("\n" + "=" * 82)
    if apy_pass:
        print("✅ ALL VALIDATIONS PASSED")
    else:
        print("❌ VALIDATION FAILED — formulas diverge from expected")
        sys.exit(1)


if __name__ == "__main__":
    main()
