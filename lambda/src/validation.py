"""Data validation at ingestion.

Validates raw data from the Bittensor endpoint before storage to prevent
corrupt or anomalous data from propagating through the pipeline.

All validation functions return (is_valid, list_of_errors) tuples.
"""

from typing import Any


def validate_metagraph(
    snapshot_data: dict[str, Any],
    previous_block: int = 0,
) -> tuple[bool, list[str]]:
    """Validate a raw metagraph snapshot before storing.

    Checks:
    - Neuron count > 0
    - Block number >= previous collection's block (chain doesn't go backwards)
    - Emission values non-negative
    - Incentive sums approximately to 1.0 for active miners (within tolerance)

    Args:
        snapshot_data: The raw snapshot dict (with metadata and data sections).
        previous_block: The block number from the previous collection for this subnet.

    Returns:
        Tuple of (is_valid, list_of_error_messages).
    """
    errors: list[str] = []

    metadata = snapshot_data.get("metadata", {})
    data = snapshot_data.get("data", {})
    neurons = data.get("neurons", [])

    # Check neuron count
    if len(neurons) == 0:
        errors.append("Empty metagraph: 0 neurons")
        return (False, errors)  # Can't validate further without neurons

    # Check block number non-decreasing
    block = metadata.get("source_block_number", 0)
    if block is not None and previous_block > 0 and block < previous_block:
        errors.append(
            f"Block went backwards: {block} < previous {previous_block}"
        )

    # Check emission values non-negative
    negative_emissions = [
        n.get("uid", "?")
        for n in neurons
        if n.get("emission", 0) < 0
    ]
    if negative_emissions:
        errors.append(
            f"{len(negative_emissions)} neurons with negative emission "
            f"(UIDs: {negative_emissions[:5]})"
        )

    # Check incentive sums approximately to 1.0 for active miners
    miner_incentives = [
        n["incentive"]
        for n in neurons
        if n.get("dividends", 0) == 0 and n.get("incentive", 0) > 0
    ]
    if miner_incentives:
        incentive_sum = sum(miner_incentives)
        if abs(incentive_sum - 1.0) > 0.01:
            errors.append(
                f"Miner incentive sum = {incentive_sum:.4f} (expected ~1.0, "
                f"tolerance 0.01)"
            )

    # Check dividends sum approximately to 1.0 for validators
    validator_dividends = [
        n["dividends"]
        for n in neurons
        if n.get("dividends", 0) > 0
    ]
    if validator_dividends:
        dividends_sum = sum(validator_dividends)
        if abs(dividends_sum - 1.0) > 0.01:
            errors.append(
                f"Validator dividends sum = {dividends_sum:.4f} (expected ~1.0, "
                f"tolerance 0.01)"
            )

    # Check for reasonable neuron count (subnets have max 256 UIDs)
    if len(neurons) > 256:
        errors.append(f"Neuron count {len(neurons)} exceeds max 256")

    return (len(errors) == 0, errors)


def validate_registration_cost(
    cost_data: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate registration cost data.

    Args:
        cost_data: Dict with 'costs' list containing per-subnet cost records.

    Returns:
        Tuple of (is_valid, list_of_error_messages).
    """
    errors: list[str] = []

    costs = cost_data.get("data", {}).get("costs", [])
    if not costs:
        errors.append("Empty registration cost data: no costs")
        return (False, errors)

    for cost in costs:
        netuid = cost.get("netuid", "?")
        reg_cost = cost.get("registration_cost_tao", -1)
        if reg_cost < 0:
            errors.append(f"Negative registration cost for netuid={netuid}: {reg_cost}")

    return (len(errors) == 0, errors)


def validate_alpha_prices(
    price_data: dict[str, Any],
) -> tuple[bool, list[str]]:
    """Validate alpha token price data.

    Args:
        price_data: Dict with 'prices' list containing per-subnet price records.

    Returns:
        Tuple of (is_valid, list_of_error_messages).
    """
    errors: list[str] = []

    prices = price_data.get("data", {}).get("prices", [])
    if not prices:
        errors.append("Empty alpha price data: no prices")
        return (False, errors)

    for price in prices:
        netuid = price.get("netuid", "?")
        alpha_price = price.get("alpha_tao_price", -1)
        if alpha_price < 0:
            errors.append(f"Negative alpha price for netuid={netuid}: {alpha_price}")

        pool_tao = price.get("pool_tao_liquidity", -1)
        if pool_tao < 0:
            errors.append(f"Negative pool liquidity for netuid={netuid}: {pool_tao}")

    return (len(errors) == 0, errors)
