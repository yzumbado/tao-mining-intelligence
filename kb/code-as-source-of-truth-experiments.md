# Code-as-Source-of-Truth: Experiment Plan

> **Status**: PLANNING
> **Created**: 2026-05-18
> **Hypothesis**: If agents extract structured knowledge directly from code (instead of reading prose docs), they make fewer mistakes, ask fewer questions, and produce more correct output on the first attempt.

---

## North Star Metric

**Ratio of productive actions to orientation actions per agent session.**

If an agent spends 30% of its context reading docs and 70% doing work → better than 60/40.

## Baseline Measurements (Before Experiments)

| Signal | Current State | How to Measure |
|--------|--------------|----------------|
| Agent orientation time | ~5-8 tool calls reading docs before first action | Count reads in session transcripts |
| Doc staleness | metrics-reference.md was wrong before generation | Compare generated vs hand-written docs |
| Decision drift | 3 dead-end approaches during deployment (repeated by agents) | Track in commit messages |
| Rework rate | Unknown | Track "undo" commits or repeated failed approaches |

---

## Phase 0: Metrics from Code ✅ DONE

**What we did**: Structured `Metric:` blocks in docstrings → `generate_metrics_reference.py` → `kb/metrics-reference.md`

**Signal observed**: Generated doc is always in sync. Manual version had already drifted (missing corrections log, wrong status on some metrics).

**Decision**: Pattern works. Expand to other domains.

---

## Phase 1: Architecture from Code

### Goal

Each Lambda handler declares its inputs, outputs, triggers, and dependencies as structured data. A generator produces a live architecture doc that's always in sync with the code.

### Hypothesis

If the architecture doc is generated from handler declarations, it will:
1. Never be stale (unlike hand-written `design.md`)
2. Catch data flow changes automatically
3. Reduce agent orientation time (structured data is faster to parse than prose)

### Success Signal

- Generated architecture matches reality (validated by comparing to hand-written design.md)
- Generated doc catches at least ONE thing the hand-written doc got wrong or omitted
- A future agent session uses the generated doc instead of reading 4 handler files

### Implementation Tasks

#### Task 1.1: Define the contract schema

**What**: Define the `__stage_contract__` dict structure that each handler will declare.

**Schema**:
```python
__stage_contract__ = {
    "name": "Processor",                          # Human-readable stage name
    "description": "Computes derived metrics from raw snapshots",
    "trigger": {
        "type": "sqs",                            # sqs | eventbridge | lambda_invoke | schedule
        "source": "tao-process-subnet",           # Queue/rule/function name
    },
    "inputs": [
        {"type": "s3", "path": "raw/metagraph/{date}/{netuid}.json", "required": True},
        {"type": "s3", "path": "raw/alpha-prices/{date}/{netuid}.json", "required": False},
        {"type": "s3", "path": "raw/hyperparameters/{date}/{netuid}.json", "required": False},
        {"type": "s3", "path": "raw/registration-costs/{date}/{netuid}.json", "required": False},
    ],
    "outputs": [
        {"type": "s3", "path": "derived/metrics/{date}/{netuid}.json"},
        {"type": "dynamodb", "key": "SUBNET#{netuid}/PROFILE#basic"},
        {"type": "dynamodb", "key": "SUBNET#{netuid}/PROFILE#winner"},
        {"type": "dynamodb", "key": "SUBNET#{netuid}/PROFILE#validator"},
    ],
    "invokes": [
        {"type": "lambda", "function": "tao-finalizer", "mode": "async"},
    ],
    "schedules": [
        {"type": "eventbridge", "name": "tao-subnet-{netuid}", "mode": "one-time"},
    ],
    "env_vars": ["AGGREGATOR_ARN", "SUBNET_COLLECTOR_ARN", "SCHEDULER_ROLE_ARN"],
    "timeout_seconds": 900,
    "memory_mb": 512,
}
```

**Acceptance criteria**: Schema is documented, covers all 4 handlers' needs.

**Effort**: 15 min (design only, no code)

#### Task 1.2: Add contracts to all 4 handlers

**What**: Add `__stage_contract__` to each handler file:
- `lambda/src/discovery/handler.py`
- `lambda/src/subnet_collector/handler.py`
- `lambda/src/processor/handler.py`
- `lambda/src/finalizer/handler.py`

**How**:
1. Read each handler's code
2. Identify: what triggers it, what it reads, what it writes, what it invokes
3. Express as the schema from Task 1.1
4. Place at module level (after imports, before functions)

**Validation**: For each handler, verify the contract matches reality by:
- Checking every S3 read/write call in the code matches a declared input/output
- Checking every boto3 client call matches a declared invoke/schedule
- Checking every `os.environ.get()` matches a declared env_var

**Acceptance criteria**: All 4 handlers have contracts. No undeclared inputs/outputs.

**Effort**: 30 min

#### Task 1.3: Write the architecture generator

**What**: Create `scripts/generate_architecture.py` that:
1. Imports all 4 handler modules (or parses them with AST)
2. Reads `__stage_contract__` from each
3. Generates `kb/architecture-live.md` with:
   - Data flow diagram (text-based, showing stage → stage connections)
   - Per-stage table (inputs, outputs, triggers)
   - Environment variables required per stage
   - Mermaid diagram (optional, for rendering)

**How**:
- Use AST parsing (same approach as metrics generator) — don't import the modules (they have AWS dependencies)
- Parse the `__stage_contract__` dict literal from each handler file
- Render markdown with tables and a text flow diagram

**Validation**:
- Run the generator
- Compare output to the hand-written architecture in `design.md` (lines 80-150)
- Document any discrepancies (this IS the success signal)

**Acceptance criteria**: Generator runs, produces readable output, matches or improves on hand-written docs.

**Effort**: 45 min

#### Task 1.4: Validate — compare generated vs hand-written

**What**: Diff the generated `kb/architecture-live.md` against the relevant sections of `.kiro/specs/.../design.md` and `handoff.md`.

**Check for**:
- Missing data flows (code does something the doc doesn't mention)
- Phantom data flows (doc mentions something the code doesn't do)
- Wrong trigger types or queue names
- Missing env vars

**Document findings** in this file under "Phase 1 Results".

**Effort**: 15 min

#### Task 1.5: Add contract validation to tests

**What**: Write a test that asserts each handler's `__stage_contract__` is consistent with the code.

**How**: For each handler:
```python
def test_processor_contract_matches_code():
    """Verify declared inputs/outputs match actual S3/DynamoDB calls."""
    source = Path("lambda/src/processor/handler.py").read_text()
    # Check that every S3 path pattern in the contract appears in the source
    # Check that every env var in the contract appears in os.environ.get() calls
```

This prevents the contract from going stale — if someone adds a new S3 read without updating the contract, the test fails.

**Acceptance criteria**: Test passes for all 4 handlers. Test would FAIL if we removed a declared input.

**Effort**: 30 min

### Phase 1 Total Effort: ~2.5 hours

### Phase 1 Results

_(To be filled after implementation)_

- [ ] Generated doc matches hand-written: YES / NO
- [ ] Discrepancies found: (list)
- [ ] Signal to expand: YES / NO

---

## Phase 2: Decision Provenance in Code

### Goal

Critical decisions live next to the code they affect, in a structured format that agents read before modifying that code.

### Hypothesis

If decisions are visible at the point of change (not buried in git log or a separate doc), agents will:
1. Not contradict previous decisions
2. Know when a workaround can be removed (revisit_when condition met)
3. Understand WHY something is the way it is without asking

### Success Signal

- An agent references a `# DECISION:` block in its reasoning when modifying nearby code
- Zero decision contradictions in the next 5 sessions that touch decided code
- At least one "revisit_when" condition is checked and acted on

### Implementation Tasks

#### Task 2.1: Identify the 5 most-violated or most-critical decisions

**What**: Review git log, handoff.md, and architecture-decisions.md to find decisions that:
- Have been violated by agents (repeated dead ends)
- Are non-obvious (an agent would reasonably make the wrong choice)
- Are near code that changes frequently

**Candidates** (from project history):
1. Emission is per-tempo, multiply by 7200/tempo for daily (violated during initial implementation)
2. Average across EARNING miners only for ROI on WTA subnets (non-obvious)
3. Validation warns, doesn't reject (violated — original code rejected 27 subnets)
4. Rankings are a live view, recomputed after each subnet (not gated on "all complete")
5. Self-scheduling loops via one-time EventBridge schedules (not cron, not Step Functions)

**Acceptance criteria**: 5 decisions selected with clear rationale for why each is critical.

**Effort**: 20 min (research git log and docs)

#### Task 2.2: Define the decision comment format

**What**: Define a lightweight structured comment format (NOT a decorator — too heavy).

**Format**:
```python
# DECISION: <short-id>
# Choice: <what we chose>
# Alternatives rejected: <what we didn't choose and why>
# Rationale: <why this choice>
# Revisit when: <condition that would change this decision>
# Evidence: <link to data, test, or live observation that validates>
```

**Constraints**:
- Must be a comment (not runtime code — zero performance impact)
- Must be parseable by a simple regex (for future generator)
- Must be within 10 lines of the code it affects (not at file top)

**Acceptance criteria**: Format defined, parseable, demonstrated on one example.

**Effort**: 10 min

#### Task 2.3: Add decision blocks to the 5 locations

**What**: Add `# DECISION:` blocks to the relevant code locations.

**Locations** (approximate — confirm by reading code):
1. `processor/handler.py` → `_build_neurons()` (tempo conversion)
2. `processor/metrics.py` → `compute_roi_estimates()` (earning miners only)
3. `validation.py` or `subnet_collector/handler.py` (warn don't reject)
4. `finalizer/handler.py` → `handle()` (live view, no gating)
5. `processor/handler.py` → `_schedule_next_collection()` (one-time schedules)

**Validation**: For each decision block:
- Verify the "choice" matches what the code actually does
- Verify "alternatives rejected" are things an agent might try
- Verify "revisit when" is a testable condition

**Acceptance criteria**: 5 blocks added, all accurate, all within 10 lines of relevant code.

**Effort**: 30 min

#### Task 2.4: (Optional) Write decision generator

**What**: Create `scripts/generate_decisions.py` that extracts all `# DECISION:` blocks and produces `kb/decisions-live.md`.

**Defer until**: We have 10+ decisions. With only 5, the blocks themselves are sufficient.

**Effort**: 30 min (when needed)

#### Task 2.5: Validate — observe agent behavior

**What**: In the next 5 agent sessions that modify code near a decision block, observe:
- Did the agent read the decision block? (check tool call logs)
- Did the agent's action contradict the decision?
- Did the agent reference the decision in its reasoning?

**How to track**: Add a note to this section after each relevant session.

**Acceptance criteria**: 3/5 sessions show positive signal (agent read and respected decision).

**Effort**: Ongoing (passive observation)

### Phase 2 Total Effort: ~1.5 hours (excluding ongoing observation)

### Phase 2 Results

_(To be filled after implementation and observation)_

- [ ] Agents read decision blocks: YES / NO (N/5 sessions)
- [ ] Decision contradictions: count
- [ ] Signal to expand: YES / NO

---

## Phase 3: Self-Describing Configuration

### Goal

Thresholds, weights, and tunable parameters carry their own rationale and validation status, so an optimization agent (or human) can make informed tuning decisions.

### Hypothesis

If configuration values include "why this value" and "has this been validated," tuning decisions will be:
1. More informed (you know what you're changing and why it was set)
2. Reversible (you know the original rationale to compare against)
3. Evidence-based (you know if the current value is a guess or proven)

### Success Signal

- When building Staking Intelligence, the weight rationale helps decide the staking-specific weights
- When we tune attractiveness score weights based on real mining data, we update `validated: True` with evidence
- An agent asked to "improve rankings" reads the rationale and makes a targeted change (not random)

### Implementation Tasks

#### Task 3.1: Refactor attractiveness weights to structured config

**What**: Replace the hardcoded weights in `_compute_attractiveness_score` (finalizer/handler.py) with a structured dict.

**Current** (in finalizer):
```python
return (yield_score * 0.4 + recoup_score * 0.25 + density_score * 0.15 +
        trend_score * 0.1 + taoflow_score * 0.1)
```

**Proposed**:
```python
# In a new file or at module level in finalizer/handler.py:
ATTRACTIVENESS_CONFIG = {
    "yield": {
        "weight": 0.40,
        "rationale": "Primary driver — net TAO earned is what we're optimizing for",
        "validated": False,
        "normalize_max": 5.0,  # TAO/day considered 'excellent'
        "normalize_max_rationale": "Based on top-10 subnet yields at launch; revisit monthly",
    },
    "recoup": {
        "weight": 0.25,
        "rationale": "Capital efficiency — registration cost must be recovered quickly when funds are limited",
        "validated": False,
        "normalize_max": 365.0,  # days — anything longer is 'terrible'
    },
    "density": {
        "weight": 0.15,
        "rationale": "Less competition = easier to earn. Secondary to yield because a high-yield crowded subnet may still be better than a low-yield empty one",
        "validated": False,
    },
    "trend": {
        "weight": 0.10,
        "rationale": "Growing emission = growing pie. Low weight because trends can reverse quickly",
        "validated": False,
    },
    "taoflow": {
        "weight": 0.10,
        "rationale": "Health signal — avoid dying subnets. Low weight because taoflow data is currently dormant",
        "validated": False,
    },
}
```

**Validation**:
- Existing tests must still pass (weights sum to 1.0, same behavior)
- The structured config produces identical rankings to the current hardcoded version

**Acceptance criteria**: Refactored, tests pass, rationale is accurate.

**Effort**: 30 min

#### Task 3.2: Add validation metadata to thresholds.py

**What**: The existing `thresholds.py` (or `get_thresholds()`) already has configurable values. Add rationale and validation status to each.

**Research first**: Read `lambda/src/thresholds.py` to understand current structure.

**Acceptance criteria**: Each threshold has `rationale` and `validated` fields.

**Effort**: 20 min

#### Task 3.3: Validate — use during Staking Intelligence build

**What**: When building the Staking Intelligence module (Task #3 on our priority list), use the structured config pattern for staking-specific weights. Compare the experience:
- Was it easier to decide weights when you could read the mining weights' rationale?
- Did the structured format help or was it noise?

**Acceptance criteria**: Subjective assessment documented here.

**Effort**: Part of Staking Intelligence work (no extra effort)

### Phase 3 Total Effort: ~1 hour

### Phase 3 Results

_(To be filled after implementation)_

- [ ] Refactored weights produce identical rankings: YES / NO
- [ ] Rationale helped during staking weight design: YES / NO
- [ ] Signal to expand: YES / NO

---

## Phase 4: Test Contracts as Specs (DEFERRED)

### When to Start

- An agent needs to autonomously modify a metric algorithm (Stage 7 OPTIMIZE)
- OR we have 20+ property tests and an agent needs to assess change impact without running them all

### What It Would Look Like

```python
@property_invariants(
    "risk_scores_bounded": "All outputs in [0.0, 1.0]",
    "immune_always_zero": "Immune miners always get risk = 0.0",
    "empty_subnet_safe": "Non-full subnets → all risks = 0.0",
)
def test_deregistration_risk_properties(...):
```

### Why Defer

- We don't have agents modifying algorithms autonomously yet
- Property tests are already readable (Hypothesis is expressive)
- Overhead of maintaining invariant annotations isn't justified until Stage 7

---

## Execution Order

| Priority | Phase | First Task | Depends On | Estimated Start |
|----------|-------|-----------|------------|-----------------|
| 1 | Phase 1 | Task 1.1 (schema) | Nothing | Today |
| 2 | Phase 2 | Task 2.1 (identify decisions) | Nothing | After Phase 1 |
| 3 | Phase 3 | Task 3.1 (refactor weights) | Nothing | During Staking Intelligence build |
| 4 | Phase 4 | Deferred | Stage 7 OPTIMIZE | Months away |

---

## Kill Criteria

**Stop expanding this approach if:**
- After Phase 1 + 2, agents still spend >50% of context on orientation
- Generated docs are never read (check tool call logs)
- Maintaining structured metadata takes more time than it saves
- The structured format becomes stale as often as prose docs did

**Expand this approach if:**
- Generated docs catch real discrepancies (Phase 1 success signal)
- Agents reference decision blocks in their reasoning (Phase 2 success signal)
- Tuning decisions are measurably better with rationale (Phase 3 success signal)

---

## Relationship to Other Work

This experiment supports but does NOT block:
- Task #1 (Fix HTML site) — independent
- Task #2 (SNS alerting) — independent
- Task #3 (Staking Intelligence) — Phase 3 integrates here
- Task #4 (Stage 2 spec) — Phase 1 architecture contracts inform the design
- Task #5 (Historical data validation) — independent
