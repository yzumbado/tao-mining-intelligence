# 6. Architecture Assessment

## What We're Proud Of

### Self-Perpetuating Subnet Loops (AD18)
Each subnet schedules its own next collection based on its tempo. No central orchestrator in the hot path. If one subnet fails, others continue independently. The Discovery Lambda is just a safety net, not a coordinator. This is the most elegant part of the architecture — it scales to 1000 subnets without any code changes.

### Pure Metrics Engine
17 algorithms, zero side effects, zero AWS calls. Every algorithm is independently testable with Hypothesis. The handler does I/O, the engine does math. This separation made it possible to add 6 new metrics in a single session without touching any infrastructure.

### StateManager as Single Access Layer
All DynamoDB access goes through one module. PK/SK patterns are encapsulated. Handlers don't know about Decimal conversion or table structure. Schema changes require updating one file. This was a refactor done in this session — previously 3 handlers accessed `_table` directly.

### Contract Smoke Test
Runs real Processor → captures output → feeds to real Finalizer. No mocks between components. This single test would have caught both CRITICAL bugs that existed for weeks. It's the highest-value test in the suite per line of code.

### Conformance Post-Conditions
5 checks run on every Finalizer invocation. Catches NaN, sort violations, missing data. Logs structured JSON. Never blocks. Zero new infrastructure. This is the foundation for a full audit system.

### Cost: $0/month
129 subnets, continuous refresh, full HTML site, CloudFront CDN — all within AWS free tier. $1 budget hard limit. No ongoing cost to operate.

### Commit Documentation Strategy
Every fix commit documents: diagnosis, root cause, failed attempts, fix, verification, when to revisit. The git log is a searchable knowledge base. Future agents don't repeat dead-end approaches.

## What's OK (Functional but Not Ideal)

### Attractiveness Score Weights
The formula works (yield×0.30 + flow×0.25 + emission×0.25 + depth×0.20) but the weights are educated guesses from Taoculator, not empirically derived. We don't have ground truth for "which subnet is actually best to mine." The score is better than the old one (which was just yield) but still hypothesis-grade.

### Emission Trend (Day-over-Day)
Works correctly but provides almost no signal — 127/129 subnets show 0% change because Bittensor emissions change slowly (30-day EMA). The metric is technically correct but practically useless for daily decisions. A 7-day or 30-day trend would be more informative.

### Taoflow Health (Dormant)
Always returns HEALTHY because we pass empty history. The metric exists, is tested, and will activate after 7 days of stake accumulation (started 2026-05-25). But for now it's dead weight in the output.

### HTML Site (Functional, Not Beautiful)
4 Jinja2 templates with Tailwind CSS. Dark theme. Shows data correctly. But no interactivity, no sorting, no filtering. It's a static dump. Good enough for agent consumption via JSON endpoints, but a human would want more.

### Single-Region Deployment
Everything in us-east-1. No disaster recovery. If the region goes down, the pipeline stops. Acceptable for a personal tool, not for a public service.

## Areas for Improvement

### Competitive Density — Dead Metric
Range [0.00017, 0.075]. Never differentiates subnets. Mixes units (count + alpha/day). Should be replaced with occupancy rate (`earning_miners / max_miners`). Backlog #14.

### No Root Proportion in Staking APY
The staking APY is still overstated because we don't model the root proportion (what % of yield goes to root stakers vs alpha stakers). Requires collecting `tao_weight` from chain. Backlog #16.

### EventBridge Schedule Retry
Both `_schedule_next_collection` and `_create_schedule` swallow all exceptions. If EventBridge throttles, the subnet's self-perpetuating loop dies silently. Should re-raise `ThrottlingException`. Backlog #15.

### 4 Orphaned Features in Code
`rental_profitability`, `entry_barrier`, `seven_day_trend`, `top_movers` — defined but never called. Should be removed from schemas and documented in commit message. Backlog #17.

### `import math` Inside Method Bodies
Two methods (`compute_net_tao_flow`, `compute_attractiveness_score`) import math inside the function body instead of at module top. Works but non-standard. Minor hygiene issue.

### E2E Test Doesn't Test Full Chain
Seeds data manually instead of running real Collector. Misses Collector→Processor format drift. The contract smoke test partially compensates, but a true end-to-end (with mocked chain) would be ideal.

### No Alerting on Conformance Failures
Post-conditions log to CloudWatch but don't trigger alarms. If rankings are corrupted, we'd only notice by checking logs manually. Should add a CloudWatch metric + alarm (costs money — deferred for free tier).
