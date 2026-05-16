"""Task 1.2: Validate Bittensor SDK v10 async connectivity.

This script proves that:
1. AsyncSubtensor connects to the public Finney endpoint
2. Metagraph retrieval works and returns expected fields
3. Registration cost is queryable
4. Hyperparameters are accessible
5. We can measure timing for capacity planning

Run: python scripts/validate_sdk.py
Requires: pip install bittensor>=10.0.0
"""

import asyncio
import json
import time
from datetime import datetime, timezone


async def validate_metagraph(netuid: int = 1):
    """Validate metagraph collection for a single subnet."""
    import bittensor as bt

    print(f"\n{'='*60}")
    print(f"VALIDATING METAGRAPH COLLECTION - Subnet {netuid}")
    print(f"{'='*60}")

    start = time.time()

    try:
        # Connect using AsyncSubtensor
        async with bt.AsyncSubtensor(network="finney") as subtensor:
            print(f"✓ Connected to Finney endpoint")
            print(f"  Network: {subtensor.network}")

            # Get current block
            block = await subtensor.get_current_block()
            print(f"  Current block: {block}")

            # Retrieve metagraph
            print(f"\n  Fetching metagraph for netuid={netuid}...")
            mg_start = time.time()
            metagraph = await subtensor.metagraph(netuid=netuid)
            mg_duration = time.time() - mg_start
            print(f"  ✓ Metagraph retrieved in {mg_duration:.2f}s")

            # Validate expected fields exist
            print(f"\n  FIELD VALIDATION:")
            fields_to_check = {
                "S (stake)": hasattr(metagraph, "S"),
                "R (rank)": hasattr(metagraph, "R"),
                "I (incentive)": hasattr(metagraph, "I"),
                "E (emission)": hasattr(metagraph, "E"),
                "C (consensus)": hasattr(metagraph, "C"),
                "T (trust)": hasattr(metagraph, "T"),
                "Tv (validator_trust)": hasattr(metagraph, "Tv"),
                "D (dividends)": hasattr(metagraph, "D"),
                "hotkeys": hasattr(metagraph, "hotkeys"),
                "coldkeys": hasattr(metagraph, "coldkeys"),
                "active": hasattr(metagraph, "active"),
                "alpha_stake": hasattr(metagraph, "alpha_stake"),
                "block_at_registration": hasattr(metagraph, "block_at_registration"),
                "blocks_since_last_step": hasattr(metagraph, "blocks_since_last_step"),
            }

            all_present = True
            for field_name, present in fields_to_check.items():
                status = "✓" if present else "✗ MISSING"
                print(f"    {status} {field_name}")
                if not present:
                    all_present = False

            # Print summary stats
            n = metagraph.n if hasattr(metagraph, "n") else len(metagraph.hotkeys)
            print(f"\n  SUBNET STATS:")
            print(f"    Total neurons: {n}")

            # Count miners vs validators
            if hasattr(metagraph, "D"):
                validators = sum(1 for d in metagraph.D if d > 0)
                miners = n - validators
                print(f"    Validators: {validators}")
                print(f"    Miners: {miners}")

            # Show top 5 miners by emission
            if hasattr(metagraph, "E") and hasattr(metagraph, "I"):
                emissions = list(enumerate(metagraph.E))
                emissions_sorted = sorted(emissions, key=lambda x: x[1], reverse=True)

                print(f"\n  TOP 5 NEURONS BY EMISSION:")
                for i, (uid, emission) in enumerate(emissions_sorted[:5]):
                    incentive = metagraph.I[uid] if uid < len(metagraph.I) else 0
                    trust = metagraph.T[uid] if hasattr(metagraph, "T") and uid < len(metagraph.T) else 0
                    hotkey = metagraph.hotkeys[uid] if uid < len(metagraph.hotkeys) else "?"
                    print(f"    #{i+1} UID={uid} emission={emission:.6f} incentive={incentive:.4f} trust={trust:.4f} hotkey={hotkey[:12]}...")

            duration = time.time() - start
            print(f"\n  Total time: {duration:.2f}s")
            print(f"  Fields present: {'ALL ✓' if all_present else 'SOME MISSING ✗'}")

            return all_present, mg_duration

    except Exception as e:
        duration = time.time() - start
        print(f"  ✗ FAILED after {duration:.2f}s: {type(e).__name__}: {e}")
        return False, 0


async def validate_registration_cost(netuid: int = 1):
    """Validate registration cost retrieval."""
    import bittensor as bt

    print(f"\n{'='*60}")
    print(f"VALIDATING REGISTRATION COST - Subnet {netuid}")
    print(f"{'='*60}")

    try:
        async with bt.AsyncSubtensor(network="finney") as subtensor:
            # Try to get burn/registration cost
            # The SDK method name may vary - try common patterns
            burn = None

            # Attempt 1: get_burn
            if hasattr(subtensor, "get_burn"):
                burn = await subtensor.get_burn(netuid=netuid)
                print(f"  ✓ get_burn() works: {burn}")

            # Attempt 2: burn (property or method)
            if burn is None and hasattr(subtensor, "burn"):
                try:
                    burn = await subtensor.burn(netuid=netuid)
                    print(f"  ✓ burn() works: {burn}")
                except TypeError:
                    pass

            # Attempt 3: query_subtensor for Burn storage
            if burn is None:
                try:
                    burn = await subtensor.substrate.query(
                        module="SubtensorModule",
                        storage_function="Burn",
                        params=[netuid],
                    )
                    print(f"  ✓ Direct storage query works: {burn}")
                except Exception as e:
                    print(f"  ⚠ Direct storage query failed: {e}")

            if burn is not None:
                # Convert from RAO to TAO if needed
                if isinstance(burn, (int, float)) and burn > 1_000_000:
                    burn_tao = burn / 1e9
                    print(f"  Registration cost: {burn_tao:.4f} TAO (raw: {burn} RAO)")
                else:
                    print(f"  Registration cost: {burn}")
                return True
            else:
                print(f"  ✗ Could not retrieve registration cost - need to investigate SDK API")
                return False

    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        return False


async def validate_hyperparameters(netuid: int = 1):
    """Validate hyperparameter retrieval."""
    import bittensor as bt

    print(f"\n{'='*60}")
    print(f"VALIDATING HYPERPARAMETERS - Subnet {netuid}")
    print(f"{'='*60}")

    try:
        async with bt.AsyncSubtensor(network="finney") as subtensor:
            # Try to get subnet hyperparameters
            hyperparams = None

            # Attempt 1: get_subnet_hyperparameters
            if hasattr(subtensor, "get_subnet_hyperparameters"):
                hyperparams = await subtensor.get_subnet_hyperparameters(netuid=netuid)
                print(f"  ✓ get_subnet_hyperparameters() works")

            # Attempt 2: subnet_hyperparameters
            if hyperparams is None and hasattr(subtensor, "subnet_hyperparameters"):
                try:
                    hyperparams = await subtensor.subnet_hyperparameters(netuid=netuid)
                    print(f"  ✓ subnet_hyperparameters() works")
                except Exception:
                    pass

            if hyperparams is not None:
                # Print available fields
                print(f"\n  HYPERPARAMETER FIELDS:")
                target_fields = [
                    "immunity_period", "tempo", "max_allowed_validators",
                    "max_allowed_miners", "min_allowed_weights",
                    "activity_cutoff", "max_weight_limit",
                ]
                for field in target_fields:
                    value = getattr(hyperparams, field, "NOT FOUND")
                    status = "✓" if value != "NOT FOUND" else "✗"
                    print(f"    {status} {field}: {value}")

                # Check burn-related params
                burn_fields = ["burn_half_life", "burn_increase_mult", "min_burn", "max_burn"]
                print(f"\n  BURN PARAMETERS:")
                for field in burn_fields:
                    # Try different naming conventions
                    value = getattr(hyperparams, field, None)
                    if value is None:
                        # Try camelCase
                        camel = "".join(w.capitalize() for w in field.split("_"))
                        camel = camel[0].lower() + camel[1:]
                        value = getattr(hyperparams, camel, "NOT FOUND")
                    status = "✓" if value != "NOT FOUND" else "?"
                    print(f"    {status} {field}: {value}")

                return True
            else:
                print(f"  ✗ Could not retrieve hyperparameters")
                # List available methods for debugging
                methods = [m for m in dir(subtensor) if "hyper" in m.lower() or "param" in m.lower()]
                print(f"  Available methods with 'hyper/param': {methods}")
                return False

    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        return False


async def validate_subnet_list():
    """Validate subnet discovery."""
    import bittensor as bt

    print(f"\n{'='*60}")
    print(f"VALIDATING SUBNET DISCOVERY")
    print(f"{'='*60}")

    try:
        async with bt.AsyncSubtensor(network="finney") as subtensor:
            # Get list of all subnets
            netuids = None

            if hasattr(subtensor, "get_all_subnet_netuids"):
                netuids = await subtensor.get_all_subnet_netuids()
                print(f"  ✓ get_all_subnet_netuids() works")
            elif hasattr(subtensor, "get_subnets"):
                netuids = await subtensor.get_subnets()
                print(f"  ✓ get_subnets() works")

            if netuids is not None:
                print(f"  Active subnets: {len(netuids)}")
                print(f"  Netuid range: {min(netuids)} to {max(netuids)}")
                print(f"  First 10: {sorted(netuids)[:10]}")
                return True, netuids
            else:
                print(f"  ✗ Could not retrieve subnet list")
                methods = [m for m in dir(subtensor) if "subnet" in m.lower()]
                print(f"  Available methods with 'subnet': {methods[:20]}")
                return False, []

    except Exception as e:
        print(f"  ✗ FAILED: {type(e).__name__}: {e}")
        return False, []


async def main():
    """Run all validation checks."""
    print(f"TAO Mining Intelligence Pipeline - SDK Validation")
    print(f"Timestamp: {datetime.now(timezone.utc).isoformat()}")
    print(f"Target: wss://entrypoint-finney.opentensor.ai:443")

    results = {}

    # 1. Subnet discovery
    success, netuids = await validate_subnet_list()
    results["subnet_discovery"] = success

    # 2. Metagraph collection (subnet 1)
    success, duration = await validate_metagraph(netuid=1)
    results["metagraph_collection"] = success
    results["metagraph_duration_seconds"] = duration

    # 3. Registration cost
    success = await validate_registration_cost(netuid=1)
    results["registration_cost"] = success

    # 4. Hyperparameters
    success = await validate_hyperparameters(netuid=1)
    results["hyperparameters"] = success

    # Summary
    print(f"\n{'='*60}")
    print(f"VALIDATION SUMMARY")
    print(f"{'='*60}")
    for key, value in results.items():
        if isinstance(value, bool):
            status = "✓ PASS" if value else "✗ FAIL"
            print(f"  {status} - {key}")
        else:
            print(f"  INFO - {key}: {value}")

    all_passed = all(v for v in results.values() if isinstance(v, bool))
    print(f"\n  {'ALL CHECKS PASSED ✓' if all_passed else 'SOME CHECKS FAILED ✗'}")
    print(f"\n  Next steps:")
    if all_passed:
        print(f"  → Proceed to Task 1.3 (DynamoDB validation)")
        print(f"  → Proceed to Task 1.4 (SQS/SNS validation)")
    else:
        print(f"  → Investigate failed checks before proceeding")
        print(f"  → Check SDK version: pip show bittensor")
        print(f"  → Check network connectivity to Finney endpoint")

    # Save results
    output = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "results": results,
        "all_passed": all_passed,
    }
    print(f"\n  Results JSON:")
    print(f"  {json.dumps(output, indent=2)}")


if __name__ == "__main__":
    asyncio.run(main())
