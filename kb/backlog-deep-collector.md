# Backlog: DeepCollector Lambda (Tiers 2-4)

**Priority**: HIGH — collecting early builds historical dataset for pattern detection
**Depends on**: Tier 1 deployed (done)
**Estimated effort**: 3-5 days

## Purpose

Collect per-UID and per-hotkey chain data that's too query-intensive for the SubnetCollector (which runs per-subnet once daily). DeepCollector runs once daily and captures the full network graph.

## Architecture

- **New Lambda**: `deep_collector/handler.py`
- **Timeout**: 15 minutes
- **Trigger**: Discovery Lambda (daily, after all subnets collected)
- **Storage**: `raw/deep/{date}/` in S3 data bucket
- **Concurrency**: 1 (avoid overloading Finney endpoint)

## Tier 2: Per-UID Data (~129,000 queries, ~215 min)

| Item | Per | Data | Intelligence Value |
|------|-----|------|-------------------|
| `Axons` | UID×subnet | IP:port of miner | Geo/hosting analysis, uptime |
| `Prometheus` | UID×subnet | IP:port of validator | Same |
| `LastUpdate` | UID×subnet | Block number | Activity/liveness signal |
| `PendingServerEmission` | UID×subnet | Unclaimed emission | Zombie miner detection |
| `NeuronCertificates` | UID×subnet | Cert data | Identity verification |

**Parallelization**: Batch 10 concurrent queries → ~22 min total.

## Tier 3: Per-Hotkey Data (~56,760 queries, ~95 min)

| Item | Per | Data | Intelligence Value |
|------|-----|------|-------------------|
| `ChildkeyTake` | hotkey×subnet | Take rate % | Exact APY per validator (replace flat 18%) |
| `ChildKeys` | hotkey×subnet | Child delegation list | Delegation hierarchy |
| `ParentKeys` | hotkey×subnet | Parent hotkey(s) | Same |
| `OwnedHotkeys` | coldkey | All hotkeys owned | Wallet mapping graph |
| `StakingHotkeys` | hotkey | Who stakes here | Delegation graph |
| `StakingColdkeys` | coldkey | What they stake to | Reverse lookup |
| `AlphaDividendsPerSubnet` | hotkey×subnet | Alpha dividends | Exact validator yield |
| `RootAlphaDividendsPerSubnet` | hotkey×subnet | Root dividends | Root yield per validator |
| `TotalHotkeyAlpha` | hotkey×subnet | Total alpha held | Concentration |
| `TotalHotkeyShares` | hotkey×subnet | Pool share | Proportional ownership |
| `PendingValidatorEmission` | hotkey×subnet | Unclaimed | Activity signal |
| `VotingPower` | hotkey | Governance weight | Influence mapping |

**Parallelization**: Batch 10 → ~10 min total.

## Tier 4: Weights & Bonds (129 bulk queries, ~10 min)

| Item | Per | Data | Intelligence Value |
|------|-----|------|-------------------|
| `Weights` | subnet | 256×256 validator→miner scores | Reverse-engineer scoring logic |
| `Bonds` | subnet | Validator-miner bond matrix | Loyalty/consistency signals |

**Size**: ~65 MB/day. Largest single dataset.

## Cost

| Resource | Monthly |
|----------|---------|
| S3 storage | ~$0.05 (2.1 GB/month) |
| Lambda compute | $0 (within free tier) |
| Data transfer | $0 (within AWS) |

## Implementation Plan

1. Create `lambda/src/deep_collector/handler.py`
2. Add DeepCollector Lambda to CDK (15 min timeout, 1024 MB memory)
3. Trigger from Discovery Lambda (daily, after normal collection cycle)
4. Store raw data at `raw/deep/{date}/{tier}/{netuid_or_entity}.json`
5. No processing initially — just accumulate raw data for future analysis

## What This Unlocks (with 30+ days of data)

- Validator yield ranking: "stake with validator X on SN44 for max yield"
- Weight stability analysis: "this validator changes scores every day vs stable for 30 days"
- Delegation graph: "3 coldkeys control 60% of SN104 stake"
- Miner migration patterns: "top miners moved from SN1 to SN44 this week"
- Zombie detection: "validator hasn't updated weights in 14 days but still earns"
- Geographic analysis: "all top miners on SN8 are in us-east-1"
