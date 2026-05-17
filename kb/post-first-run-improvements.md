# Post-First-Run Improvement Plan

## Problems Found During First Live Deployment (2026-05-17)

### Problem 1: Cycle Never Completes When Subnets Fail

**Symptom**: Finalizer waits for `subnets_complete == subnets_total` (129), but
27 subnets failed validation + 3 timed out. Cycle stuck at 102/129 forever.

**Impact**: No rankings, no briefing, no site — until manual intervention.

**Fix — Partial Completion with Timeout**:

```
Option A: Deadline-based finalization
- Orchestrator records cycle_start_time
- Finalizer checks: if (now - cycle_start_time > 30 min) AND (subnets_complete > 0):
    finalize with whatever we have
- Add "subnets_failed" count to cycle record

Option B: Explicit failure tracking
- SubnetCollector publishes failure messages (not just success)
- Cycle tracks: subnets_complete + subnets_failed = subnets_total → finalize
- Rankings include only successful subnets

Recommendation: Option B — explicit is better than timeout-based.
```

**Implementation**:
1. SubnetCollector: on validation failure, send SQS message with `status: "skipped"`
2. Processor: on receiving "skipped", increment a `subnets_skipped` counter
3. Finalizer trigger condition: `subnets_complete + subnets_skipped >= subnets_total`
4. Briefing includes: "27 subnets skipped (validation), 102 processed"

---

### Problem 2: SubnetCollector Timeout (60s too short for some subnets)

**Symptom**: 3 subnets (48, 120) hit 60s timeout. Memory also near-maxed (510/512MB).

**Fix — Already applied via console**: Timeout=90s, Memory=1024MB.

**Permanent fix**: Update CDK to match:
```python
timeout=Duration.seconds(90),
memory_size=1024,
```

Also update the SQS visibility timeout to be > Lambda timeout (currently 90s, should be 120s).

---

### Problem 3: ROI Shows 0 for All Subnets

**Symptom**: Rankings show `net_tao_yield: 0.0` for all 102 subnets.

**Root cause hypothesis**: The Processor reads `raw/alpha-prices/{date}.json` as a
consolidated file, but the SubnetCollector stores alpha prices per-subnet in
individual files. The Processor can't find the consolidated file → alpha_price=0 → ROI=0.

**Fix**: Either:
- (A) SubnetCollector writes a consolidated alpha-prices file (requires coordination)
- (B) Processor reads per-subnet alpha price files
- (C) Orchestrator collects alpha prices once (before dispatching subnets)

**Recommendation**: Option C — alpha prices are global data, not per-subnet.
The Orchestrator should collect them once and store the consolidated file.
SubnetCollectors then only collect metagraph + hyperparameters.

---

### Problem 4: No Site Generated

**Symptom**: `site/` bucket is empty after Finalizer completes.

**Root cause hypothesis**: Site generation requires subnet profiles in DynamoDB
(category, taoflow_status, reward_model). These are written by the Processor,
but the Finalizer may not be reading them correctly, or the site generation
is gated on data that doesn't exist yet (first run = no historical profiles).

**Fix**: Debug the site generation path in the Finalizer. Likely needs a
graceful fallback when profiles don't exist yet.

---

### Problem 5: 27 Subnets Failed Validation

**Symptom**: `Miner incentive sum = 0.5786 (expected ~1.0, tolerance 0.01)`

**Root cause**: Our validation assumes incentive sums to ~1.0, but some subnets
have different incentive distributions (partial validators, new subnets with
few miners). The tolerance is too strict.

**Fix**: Relax the incentive sum validation or make it a warning instead of
a rejection. The data is still valid — the incentive distribution just doesn't
sum to 1.0 on all subnets.

---

## Priority Order

| # | Fix | Effort | Impact |
|---|-----|--------|--------|
| 1 | Relax incentive validation (27 subnets recovered) | 10 min | High |
| 2 | CDK: timeout=90s, memory=1024MB permanent | 5 min | Medium |
| 3 | Partial completion logic (Option B) | 1 hour | High |
| 4 | Fix alpha price data flow (ROI=0 bug) | 30 min | High |
| 5 | Debug site generation | 30 min | Medium |

## Caching / Resume Strategy

**Current state**: If the pipeline fails mid-cycle, there's no way to resume.
Re-invoking the Orchestrator creates a new cycle (idempotency blocks duplicate
cycle_id). The only option is to delete the cycle record and re-run everything.

**Proposed improvement — Resume from checkpoint**:

1. **Orchestrator**: Before dispatching, check which subnets already have raw
   snapshots in S3 for today. Only dispatch missing ones.
2. **Processor**: Already idempotent (overwrites derived metrics). Safe to re-run.
3. **Finalizer**: Already idempotent (overwrites rankings/briefing). Safe to re-run.

**Implementation**:
```python
# In Orchestrator._async_handle():
existing = _storage.list_keys(f"raw/metagraph/{date}/")
already_collected = {int(k.split("/")[-1].replace(".json","")) for k in existing}
to_dispatch = [n for n in netuids if n not in already_collected]
```

This gives us **free resume** — if the pipeline crashes at subnet 50/129, re-running
only dispatches the remaining 79. No wasted work, no duplicate collection.
