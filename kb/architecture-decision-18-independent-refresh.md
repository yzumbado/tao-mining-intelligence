# Architecture Decision 18: Independent Subnet Refresh over Batch Cycle

**Date**: 2026-05-17
**Status**: Proposed
**Deciders**: yvvargas + Kiro

## Context

The pipeline was originally designed as a **daily batch job**: EventBridge triggers once at 00:00 UTC, an Orchestrator discovers all subnets, dispatches them all, waits for all to complete, then a Finalizer generates aggregate outputs.

First live deployment (2026-05-17) exposed fundamental problems with this model:
- 27/129 subnets failed validation → cycle stuck forever (Finalizer waits for all)
- 3 subnets timed out → same stuck cycle
- Manual intervention required to produce any output
- A single subnet failure blocks intelligence for all 128 other subnets
- Data is 24 hours stale by design (daily refresh)

The batch model creates **artificial coupling** between subnets that have zero data dependencies on each other. Subnet 1's metagraph has no relationship to subnet 48's metagraph. There is no reason to wait for one before processing another.

## Decision

Replace the batch cycle model with **self-scheduling independent subnet loops**.

Each subnet is a self-perpetuating process:
1. EventBridge Scheduler fires a one-time schedule for subnet N
2. SubnetCollector collects that subnet's data
3. Processor computes metrics for that subnet
4. Aggregator recomputes rankings from all current profiles and regenerates the site
5. Processor creates the next one-time schedule (now + tempo duration)
6. Loop continues indefinitely

A lightweight Discovery Lambda runs hourly as a safety net: detects new subnets (seeds their first schedule) and stale subnets (re-seeds loops that died).

## Key Properties

- **Zero coupling between subnets**: Subnet 1 failing has no impact on subnet 4
- **Freshness proportional to tempo**: Fast subnets refresh every ~20 min, slow ones every ~72 min
- **Configurable max staleness**: No subnet older than N hours (default: 4), enforced by Discovery Lambda
- **Self-healing**: If a loop dies (Lambda crash, chain timeout), Discovery Lambda re-seeds it within 1 hour
- **Rankings are a live view**: Computed from whatever profiles exist at computation time, not gated on "all complete"
- **No orchestrator in the hot path**: No central coordinator that can become a bottleneck or single point of failure

## Alternatives Considered

### Alternative A: Fix the batch model (add partial completion)
- Track failures explicitly, finalize when complete + failed = total
- Pros: Minimal code change
- Cons: Still daily (stale data), still coupled (one slow subnet delays output), doesn't address the fundamental design mismatch
- **Rejected**: Treats symptoms, not root cause

### Alternative B: EventBridge rate(5 min) poller + DynamoDB "due" check
- Single Lambda runs every 5 min, queries which subnets are due, dispatches them
- Pros: Simple, single scheduler
- Cons: Reintroduces a central orchestrator, 5-min granularity, central point of failure
- **Rejected**: Still has a coordinator in the hot path

### Alternative C: SQS with delay for self-scheduling
- Each subnet sends itself a delayed SQS message for next run
- Pros: Uses existing infrastructure
- Cons: SQS max delay is 15 minutes (our cadences are 20-240 min), recursive Lambda→SQS→Lambda is an anti-pattern AWS warns against
- **Rejected**: Technical limitation (15 min cap) makes it unworkable

### Chosen: EventBridge Scheduler one-time schedules
- Each subnet creates its own next schedule after processing
- Pros: Exact timing, no wasted invocations, self-cleaning (ActionAfterCompletion=DELETE), truly independent, supports any delay
- Cons: Need IAM permissions for scheduler:CreateSchedule, slightly more complex than SQS
- Cost: $1/million invocations (~23K/month = $0.02/month)

## Consequences

### Positive
- Data freshness improves from 24h to 20-240 minutes (per subnet tempo)
- No single subnet can block the entire pipeline
- Self-healing without manual intervention
- Rankings always reflect latest available data
- Simpler mental model: each subnet is its own independent pipeline
- Aligns with the project's purpose: deterministic collection layer, not intelligence layer

### Negative
- More EventBridge schedules to manage (129 concurrent)
- Aggregator runs more frequently (~780 times/day vs 1/day) — but it's fast (<1s)
- Harder to answer "did the pipeline run today?" — replaced by "is any subnet stale?"
- Existing tests for Orchestrator/Finalizer need rewriting
- Documentation overhaul required (7 requirements, design doc, handoff, operations)

### Neutral
- Cost stays at $0/month (all within free tier)
- MetricsEngine unchanged (pure functions)
- DynamoDB schema unchanged (already per-subnet)
- S3 paths unchanged

## Infrastructure Changes

| Remove | Add |
|--------|-----|
| Orchestrator Lambda | Discovery Lambda (hourly) |
| EventBridge daily cron | EventBridge hourly Discovery + per-subnet one-time schedules |
| SQS collection queue + DLQ | — |
| SNS subnet-processed topic | — |
| SQS completion-tracker queue + DLQ | — |
| CloudWatch collection DLQ alarm | CloudWatch staleness alarm |
| CloudWatch completion DLQ alarm | — |

## Configurable Parameters

```
PK=CONFIG, SK=REFRESH_POLICY
{
    "max_staleness_hours": 4,
    "min_refresh_interval_minutes": 15,
    "discovery_cadence_minutes": 60
}
```

Editable via AWS Console (DynamoDB) without redeployment.

## Validation Approach

- Relax metagraph validation from hard rejection to warning + quality flag
- Log structured quality metrics for monitoring
- Subnets with quality warnings still get processed (data is usable, just non-standard)
- Daily briefing includes data quality summary

## Agent Interface

- `/llms.txt` at site root — machine-readable index for AI agents
- `/data/metadata.json` — per-subnet freshness timestamps
- `/data/rankings.json` — current rankings (recomputed on each subnet update)
- `/data/subnets/{netuid}.json` — individual subnet profiles
- All outputs include `collected_at`, `processed_at`, `source_block` in metadata

## When to Revisit

- If EventBridge Scheduler hits limits (1M schedules/month) — unlikely at 23K/month
- If Aggregator becomes a bottleneck (running 780 times/day) — could batch with SQS
- If we need sub-minute freshness — would need a persistent process, not Lambda
- If AWS adds SQS delays > 15 minutes — could simplify back to SQS-only
