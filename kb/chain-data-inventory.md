# Chain Data Inventory — Bittensor SubtensorModule

**Created**: 2026-06-01
**Source**: Live chain query via `sub.substrate.get_metadata()`
**Total storage items**: 217

## What We Currently Collect (~37 items)

### Via Metagraph (`sub.metagraph(netuid)`)
- Stake (S), Incentive (I), Emission (E), Consensus (C), Dividends (D)
- ValidatorTrust (Tv), Active, BlockAtRegistration, ValidatorPermit
- Hotkeys, Coldkeys, AlphaStake (AS), TotalStake (TS)
- SubnetworkN (n, num_uids), MaxAllowedUids (max_uids)
- BlocksSinceLastStep, block (current block)

### Via `get_subnet_hyperparameters(netuid)`
- Tempo, ImmunityPeriod, MaxAllowedValidators, MinAllowedWeights
- MaxWeightsLimit, Difficulty, MaxBurn, MinBurn
- MaxRegistrationsPerBlock, TargetRegistrationsPerInterval
- AdjustmentInterval, AdjustmentAlpha, BondsMovingAverage
- Kappa, Rho, CommitRevealWeightsEnabled, WeightsVersionKey
- WeightsSetRateLimit, RegistrationAllowed, ServingRateLimit

### Via Direct `substrate.query()`
- SubnetTAO (pool TAO per subnet + root total)
- SubnetAlphaIn (pool alpha liquidity)
- SubnetAlphaOut (alpha outstanding)
- TaoWeight (global 0.18)
- Burn (registration cost per subnet)
- get_subnet_price (derived from SubnetTAO/SubnetAlphaIn)

---

## 🔴 Should Collect — Directly Improves Scoring (12 items)

| Item | Type | Params | Value Example | Impact |
|------|------|--------|---------------|--------|
| `SubnetEmaTaoFlow` | Per-subnet | [netuid] | Signed I128 | THE signal that determines emission allocation since dTAO. Authoritative vs our DIY EMA from daily snapshots. |
| `SubnetOwnerCut` | Global | [] | 11796 (18.00%) | Owner takes 18% BEFORE miner/validator 41/41 split. Our APY is overstated without this. |
| `BlockEmission` | Global | [] | 1.0 TAO/block (7200/day) | Actual emission rate. We assume; should verify. Changes at halvings. |
| `TotalStake` | Global | [] | 7,308,954 TAO | Network-wide staking context for relative attractiveness. |
| `SubnetVolume` | Per-subnet | [netuid] | U64 (raw) | Pool trading volume. Real liquidity signal vs our alpha_price proxy. |
| `RegistrationsThisInterval` | Per-subnet | [netuid] | int (0-N) | Direct registration pressure. Better than 24h churn estimate. |
| `SubnetOwner` | Per-subnet | [netuid] | SS58 coldkey | Owner identity. Cross-ref with miner/validator coldkeys → self-mining detection. |
| `SubnetMovingPrice` | Per-subnet | [netuid] | I128 (fixed-point) | EMA-smoothed alpha price. Less noisy for trend analysis. |
| `SubnetTaoInEmission` | Per-subnet | [netuid] | U64 | TAO emission allocated to this subnet per block. |
| `SubnetAlphaOutEmission` | Per-subnet | [netuid] | U64 | Alpha emission going to participants per block. |
| `SubnetIdentitiesV3` | Per-subnet | [netuid] | Struct | On-chain subnet name/description. Free metadata without GitHub. |
| `SubnetTaoFlow` | Per-subnet | [netuid] | I64 | Raw (non-EMA) TAO flow. Instantaneous staking direction. |

---

## 🟡 Useful for Future Stages (25 items)

| Item | Type | Params | What It Contains | Future Use |
|------|------|--------|-----------------|------------|
| `Weights` | Per-subnet | [netuid] | Full validator→miner weight matrix (256×256) | Stage 2: reverse-engineer validator scoring logic |
| `ChildKeys` | Per-hotkey | [hotkey, netuid] | List of child hotkeys delegated to | Validator delegation tree, nominator yield |
| `ParentKeys` | Per-hotkey | [hotkey, netuid] | Parent hotkey(s) | Same — who delegates to whom |
| `ChildkeyTake` | Per-hotkey | [hotkey, netuid] | U16 (take %) | Replace flat 18% assumption with exact per-validator take |
| `MaxDelegateTake` | Global | [] | 18% | Validate our assumption |
| `MinDelegateTake` | Global | [] | % | Lower bound on take |
| `Bonds` | Per-subnet | [netuid] | Validator-miner bond matrix | Consensus mechanism internals, loyalty signals |
| `Axons` | Per-UID | [netuid, uid] | IP:port of miner | Stage 6: verify miner is online, detect geo |
| `Prometheus` | Per-UID | [netuid, uid] | IP:port of validator | Same |
| `OwnedHotkeys` | Per-coldkey | [coldkey] | List of all hotkeys | Wallet mapping — "who controls what" graph |
| `StakingHotkeys` | Per-hotkey | [hotkey] | Coldkeys staking to it | Delegation graph — who nominates whom |
| `StakingColdkeys` | Per-coldkey | [coldkey] | Hotkeys being staked to | Reverse delegation lookup |
| `AlphaDividendsPerSubnet` | Per-hotkey-subnet | [hotkey, netuid] | Alpha dividends earned | Exact yield per validator per subnet |
| `RootAlphaDividendsPerSubnet` | Per-hotkey-subnet | [hotkey, netuid] | Root dividends | Root staker yield per subnet |
| `VotingPower` | Per-hotkey | [hotkey] | U64 | Governance influence |
| `SubnetLeases` / `SubnetLeaseShares` | Per-subnet | [netuid] | Lease data | New leasing mechanism |
| `TotalHotkeyAlpha` | Per-hotkey-subnet | [hotkey, netuid] | Total alpha held | Concentration analysis per validator |
| `TotalHotkeyShares` / `V2` | Per-hotkey-subnet | [hotkey, netuid] | Share of pool | Proportional ownership |
| `LastUpdate` | Per-UID | [netuid, uid] | Block number | When each neuron last set weights. Activity/liveness signal. |
| `NeuronCertificates` | Per-UID | [netuid, uid] | Cert data | Identity verification |
| `PendingValidatorEmission` | Per-hotkey-subnet | [hotkey, netuid] | Unclaimed emission | Validator claiming behavior |
| `PendingServerEmission` | Per-UID | [netuid, uid] | Unclaimed miner emission | Miner claiming behavior |
| `SubnetProtocolAlpha` / `SubnetProtocolFlow` | Per-subnet | [netuid] | Protocol-level alpha/flow | Protocol economics |
| `SubnetExcessTao` | Per-subnet | [netuid] | Excess TAO in pool | Pool health signal |
| `SubnetLocked` | Per-subnet | [netuid] | Locked TAO | Capital lockup per subnet |
| `MechanismEmissionSplit` | Global? | [] | Split ratios | How emission divides between mechanisms |

---

## ⚪ Discarding — No Mining Intelligence Value (143 items)

### Rate Limiters & Anti-Spam
TxRateLimit, WeightsSetRateLimit, StakingOperationRateLimiter, LastRateLimitedBlock,
TxChildkeyTakeRateLimit, TxDelegateTakeRateLimit, LastTxBlock, LastTxBlockChildKeyTake,
LastTxBlockDelegateTake, NetworkRateLimit, OwnerHyperparamRateLimit,
WeightsVersionKeyRateLimit, TransactionKeyLastBlock

### Migration & Feature Flags
HasMigrationRun, CommitRevealWeightsVersion, Yuma3On, SubtokenEnabled,
TransferToggle, NetTaoFlowEnabled, LiquidAlphaOn, OwnerCutEnabled,
OwnerCutAutoLockEnabled, AutoParentDelegationEnabled, VotingPowerTrackingEnabled,
VotingPowerDisableAtBlock, NetworkPowRegistrationAllowed, NetworkRegistrationAllowed,
NetworkRegistrationStartBlock, SubnetEmissionEnabled

### Coldkey Swap (Security Mechanism)
ColdkeySwapAnnouncements, ColdkeySwapDisputes, ColdkeySwapAnnouncementDelay,
ColdkeySwapReannouncementDelay

### Lock/Decay Mechanics
DecayingHotkeyLock, DecayingOwnerLock, DecayingLock, HotkeyLock, OwnerLock,
Lock, LargestLocked, UnlockRate, MaturityRate

### Network/Subnet Registration Config
NetworkImmunityPeriod, NetworkLastLockCost, NetworkLockReductionInterval,
NetworkMinLockCost, DissolveNetworkScheduleDuration, NetworkRegisteredAt,
NetworksAdded, RegisteredSubnetCounter, NextSubnetLeaseId

### Internal Block-Level Counters
RegistrationsThisBlock, BurnRegistrationsThisInterval, POWRegistrationsThisInterval,
RAORecycledForRegistration, LastAdjustmentBlock, FirstEmissionBlockNumber,
LastMechansimStepBlock

### Commit-Reveal Weight Internals
CRV3WeightCommits, CRV3WeightCommitsV2, WeightCommits, TimelockedWeightCommits,
RevealPeriodEpochs

### Difficulty/Burn Tuning
MaxDifficulty, MinDifficulty, BurnHalfLife, BurnIncreaseMult, ScalingLawPower,
FlowEmaSmoothingFactor, FlowNormExponent, TaoFlowCutoff, EMAPriceHalvingBlocks

### Auto-Stake Config
AutoStakeDestination, AutoStakeDestinationColdkeys

### Governance/Voting Config
VotingPowerEmaAlpha, NumRootClaim, RootClaimType, RootClaimable,
RootClaimableThreshold, RootClaimed, RootProp

### Internal Indices & Bookkeeping
AlphaMapLastKey, AlphaV2MapLastKey, NextStakeJobId, NumStakingColdkeys,
StakingColdkeysByIndex, LastColdkeyHotkeyStakeBlock, Uids, UsedWork,
:__STORAGE_VERSION__:, Alpha, AlphaV2, AlphaValues, SubnetAlphaInProvided,
SubnetTaoProvided, SubnetRootSellTao, SubnetUidToLeaseId, PendingRootAlphaDivs,
PendingOwnerCut, PendingChildKeys, PendingChildKeyCooldown

### Subnet Governance Limits
SubnetLimit, MaxMechanismCount, MechanismCountCurrent, MinNonImmuneUids,
MinAllowedUids, ImmuneOwnerUidsLimit, ValidatorPruneLen, ActivityCutoff,
MinActivityCutoff, AdminFreezeWindow, StartCallDelay

### Identity/Display
IdentitiesV2, AssociatedEvmAddress, TokenSymbol

### Issuance/Totals (Static/Slow-Changing)
TotalIssuance, TotalNetworks, CKBurn, RecycleOrBurn

### Misc
Delegates, IsNetworkMember, LoadedEmission, StakeThreshold, StakeWeight,
NominatorMinRequiredStake, LastHotkeyEmissionOnNetuid, LastHotkeySwapOnNetuid,
MaxChildkeyTake, MinChildkeyTake, MinChildkeyTakePerSubnet, BondsResetOn,
BondsPenalty, SubnetMovingAlpha, AccumulatedLeaseDividends
