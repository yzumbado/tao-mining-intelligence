"""Validate all SDK fields we use against our schema assumptions."""
import asyncio
import bittensor as bt


async def main():
    print("=== SDK FIELD VALIDATION vs OUR SCHEMA ===\n")

    async with bt.AsyncSubtensor(network="finney") as sub:
        mg = await sub.metagraph(netuid=1)
        hp = await sub.get_subnet_hyperparameters(netuid=1)
        price = await sub.get_subnet_price(netuid=1)

        print("--- METAGRAPH FIELDS ---")
        checks = [
            ("S (stake)", mg.S),
            ("I (incentive)", mg.I),
            ("E (emission)", mg.E),
            ("C (consensus)", mg.C),
            ("D (dividends)", mg.D),
            ("Tv (validator_trust)", mg.Tv),
            ("AS (alpha_stake)", mg.AS),
            ("TS (total_stake)", mg.TS),
            ("hotkeys", mg.hotkeys),
            ("coldkeys", mg.coldkeys),
            ("active", mg.active),
            ("block_at_registration", mg.block_at_registration),
            ("blocks_since_last_step", mg.blocks_since_last_step),
            ("n (count)", mg.n),
        ]

        for name, val in checks:
            t = type(val).__name__
            try:
                if hasattr(val, "__len__") and not isinstance(val, (str, int, float)):
                    ln = len(val)
                    s = f"array[{ln}] sample={type(val[0]).__name__}({val[0]})" if ln > 0 else "empty"
                    print(f"  ✓ {name:30s} → {s}")
                else:
                    print(f"  {'✓' if val is not None else '✗'} {name:30s} → scalar {t}({val})")
            except TypeError:
                print(f"  ? {name:30s} → {t}({val})")

        print("\n--- HYPERPARAMETERS ---")
        hp_attrs = sorted(
            [a for a in dir(hp) if not a.startswith("_") and not callable(getattr(hp, a))]
        )
        for a in hp_attrs:
            v = getattr(hp, a)
            print(f"  {a:35s} = {v}")

        print(f"\n--- PRICE ---")
        print(f"  get_subnet_price(1) = {price} (float={float(price):.8f})")

        print(f"\n--- STORAGE QUERIES ---")
        burn = await sub.substrate.query("SubtensorModule", "Burn", [1])
        tao_pool = await sub.substrate.query("SubtensorModule", "SubnetTAO", [1])
        alpha_pool = await sub.substrate.query("SubtensorModule", "SubnetAlphaIn", [1])
        print(f"  Burn(1) = {burn} → {int(burn)/1e9:.6f} TAO")
        print(f"  SubnetTAO(1) = {tao_pool} → {int(tao_pool)/1e9:.2f} TAO")
        print(f"  SubnetAlphaIn(1) = {alpha_pool} → {int(alpha_pool)/1e9:.2f} alpha")


if __name__ == "__main__":
    asyncio.run(main())
