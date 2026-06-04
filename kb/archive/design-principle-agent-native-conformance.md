# Design Principle: Agent-Native Continuous Conformance

**Status**: PROPOSAL (brainstorm output, 2026-05-19)
**Context**: TAO Mining Intelligence Pipeline — self-monitoring POC

---

## The Thesis

Software systems should leverage the complementary strengths of agents and humans. Agents excel at continuous, repetitive, exhaustive work — verification, data collection, pattern detection, 24/7 vigilance. Humans excel at judgment, prioritization, strategic decisions, and system evolution. The design principle is **collaboration**: assign each task to whoever does it best.

Current systems are designed as if humans do everything — build, test, monitor, fix, decide. This wastes human attention on work agents can do better (repetitive verification, exhaustive checking, overnight vigilance) and forces agents into roles that need human judgment (prioritization, architectural decisions, "should we even fix this?").

**The design principle**: Build systems where agents continuously verify correctness, detect drift, collect evidence, and surface findings — while humans review, triage, decide what matters, and direct how the system evolves. The human-facing outputs (dashboards, briefings, HTML site) are the **collaboration interface** — the window through which humans observe and steer.

---

## The Collaboration Model

```
Agents (24/7, tireless, exhaustive)     Humans (strategic, decisive, creative)
───────────────────────────────────     ──────────────────────────────────────
Collect subnet data continuously        Decide what data matters
Verify output correctness               Define what "correct" means
Detect spec↔code drift                  Decide if drift is intentional (descope)
Find edge cases in live data            Decide which edge cases matter
Analyze commit history for patterns     Decide what patterns mean for architecture
Propose fixes with full diagnosis       Approve, redirect, or rethink
Execute approved work                   Review results
Report status (audit_report.json)       Triage: fix / ignore / redesign
Generate HTML dashboard                 Read it, spot strategic opportunities
```

Neither side is subordinate. The HTML site, the daily briefing, the audit report — these are **collaboration surfaces**, not "legacy human interfaces." They exist because humans need a window into what the agents are doing, and agents need human direction on what to do next.

---

## What We're Leveraging

### Agent strengths (assign these tasks to agents):

| Capability | What it enables | Example in our pipeline |
|-----------|-----------------|------------------------|
| Reads entire codebase in seconds | Exhaustive audits, not sampled | Check ALL 43 requirements against ALL output fields |
| Reloads full context from artifacts | Every audit starts with complete knowledge | No "I forgot what we decided last week" |
| Runs 24/7, triggered by events | Continuous verification between human sessions | Catch the empty-badges bug at 2am, not 2 days later |
| Coordinates via structured data | No meetings needed for handoff | Finding → queue → agent picks up → fix proposed |
| Analyzes entire commit history at once | Pattern detection across time | "This class of bug has happened 3 times" |
| Never fatigues on repetitive checks | Verify every field, every path, every time | No "I'll check that later" |
| Large working context (~200K tokens) | Hold entire system model in one session | Trace a field from collector → processor → finalizer → site |

### Human strengths (reserve these for humans):

| Capability | What it enables | Example in our pipeline |
|-----------|-----------------|------------------------|
| Judgment and prioritization | Decide what matters | "This drift is intentional — we descoped it" |
| Strategic thinking | System evolution | "We need Stage 2 before this field can be populated" |
| Creative problem-solving | Novel architecture | "What if the system monitored itself?" |
| Risk assessment | Safe deployment | "Don't auto-fix this, it could break consumers" |
| Domain expertise | Correct interpretation | "0.0005 TAO reg cost is normal, not a bug" |
| Motivation and direction | What to build next | Triage audit report → prioritize backlog |

### What changes vs traditional systems:

- **Tests run at build time** → Agents ALSO verify continuously against production
- **Code review happens once (at PR)** → Agents ALSO check continuously against evolving requirements
- **Monitoring checks metrics** → Agents ALSO check semantic correctness
- **Bugs are reported by users** → Agents detect them before any user sees them
- **Humans do the tedious verification** → Agents do it; humans review findings and decide

---

## What We're Building Toward

### The Conformance Loop

```
┌─────────────────────────────────────────────────────────────────┐
│                    CONTINUOUS CONFORMANCE LOOP                    │
│                                                                  │
│   ┌──────────┐    ┌──────────┐    ┌──────────┐    ┌─────────┐ │
│   │  SPECS   │    │   CODE   │    │  OUTPUT  │    │  TESTS  │ │
│   │          │    │          │    │          │    │         │ │
│   │design.md │◄──►│ src/*.py │◄──►│ live data│◄──►│ tests/  │ │
│   │reqs.md   │    │ handler  │    │ CloudFrt │    │ mocks   │ │
│   │decisions │    │ metrics  │    │ DynamoDB │    │fixtures │ │
│   └────┬─────┘    └────┬─────┘    └────┬─────┘    └────┬────┘ │
│        │               │               │               │       │
│        └───────────────┴───────────────┴───────────────┘       │
│                              │                                   │
│                              ▼                                   │
│                    ┌──────────────────┐                          │
│                    │  AUDITOR AGENT   │                          │
│                    │                  │                          │
│                    │  Picks dimension │                          │
│                    │  Executes probe  │                          │
│                    │  Classifies gap  │                          │
│                    │  Emits finding   │                          │
│                    └────────┬─────────┘                          │
│                             │                                    │
│                             ▼                                    │
│              ┌──────────────────────────────┐                   │
│              │     FINDINGS + EVIDENCE      │                   │
│              │                              │                   │
│              │  • Structured diagnosis      │                   │
│              │  • Live data samples         │                   │
│              │  • File:line references      │                   │
│              │  • Verification commands     │                   │
│              │  • Suggested fix category    │                   │
│              └──────────────┬───────────────┘                   │
│                             │                                    │
│                    ┌────────┴────────┐                           │
│                    ▼                 ▼                            │
│           ┌──────────────┐  ┌──────────────┐                   │
│           │  AUTO-FIX    │  │  WORK QUEUE  │                   │
│           │  (trivial)   │  │  (complex)   │                   │
│           │              │  │              │                   │
│           │ Fix + test + │  │ Agent picks  │                   │
│           │ commit + PR  │  │ up, plans,   │                   │
│           └──────────────┘  │ implements   │                   │
│                             └──────────────┘                   │
└─────────────────────────────────────────────────────────────────┘
```

---

## The Five Audit Dimensions

### Dimension 1: Spec ↔ Code (Requirements Traceability)

**What it does**: Parses requirements.md and design.md, extracts machine-readable assertions, verifies them against code and output.

**How it works for agents (vs humans)**:
- Human: reads requirements doc, mentally maps to code, spots gaps occasionally
- Agent: parses ALL 43 requirements, extracts every "SHALL" statement, maps each to a code path or output field, verifies continuously

**Example assertions extracted from our requirements.md**:
```
REQ-6.4: rankings SHALL include [netuid, net_tao_yield, days_to_recoup,
         thirty_day_projected_tao, active_miner_count, registration_cost,
         competitive_density, emission_trend_7day, alpha_tao_price,
         alpha_liquidity, attractiveness_score]

VERIFY: GET /data/rankings.json → assert all fields present in each entry
STATUS: PARTIAL — missing active_miner_count, registration_cost, alpha_liquidity, emission_trend_7day
```

### Dimension 2: Code ↔ Output (Semantic Correctness)

**What it does**: Reads the code to understand what SHOULD be produced, then checks live output.

**Agent advantage**: Can literally execute the code path mentally (trace through functions) and predict the output shape, then compare to reality. A human would need to run the code or read very carefully.

### Dimension 3: Test ↔ Production (Test Honesty)

**What it does**: Compares test data factories to live production data shapes.

**Agent advantage**: Can read ALL test files and ALL production outputs simultaneously. A human would sample. The agent checks exhaustively.

**Key check**: For every field in a test mock, verify the production code actually produces that field. For every value range in production, verify tests exercise that range.

### Dimension 4: History ↔ Present (Commit Archaeology)

**What it does**: Analyzes git history to find patterns that predict bugs.

**Agent advantage**: Can read the entire commit history (60+ commits) in one pass, correlate patterns across time, and identify:

- **Orphaned intentions**: A commit message says "add field X" but the field never appears in downstream consumers
- **Incomplete refactors**: A rename happened in 3/5 files (grep for old name still finds hits)
- **Documented-but-not-implemented**: Commit says "TODO: propagate source_block" but no follow-up commit does it
- **Test-code divergence**: Test was updated but the code it tests wasn't (or vice versa)
- **Repeated patterns**: Same type of bug fixed 3 times → systemic issue not addressed

**Specific checks**:
```python
# Find commits that mention a field but don't touch all relevant files
for commit in git_log:
    if "source_block" in commit.message:
        files_touched = commit.files_changed
        files_that_use_field = grep("source_block", codebase)
        orphaned = files_that_use_field - files_touched
        if orphaned:
            emit_finding("incomplete_propagation", commit, orphaned)

# Find design decisions that were never fully implemented
for decision in parse_architecture_decisions():
    implementation_commits = find_commits_mentioning(decision.id)
    if decision.status == "APPROVED" and not implementation_commits:
        emit_finding("unimplemented_decision", decision)
```

### Dimension 5: Live Data → Test Fixtures (Reality Grounding)

**What it does**: Samples production data and compares to test assumptions. Saves interesting samples as fixtures.

**Agent advantage**: Can fetch live data, compute statistics, and compare to test ranges — all in one invocation. Humans would need to write scripts, run them, interpret results.

**The flywheel**:
```
Live data sample → Statistical profile → Compare to test fixtures
    │                                           │
    │  "Production has values 0.00001-104.3"    │
    │  "Tests only use 0.5-10.0"               │
    │                                           │
    ▼                                           ▼
Save edge cases as fixtures          Flag untested ranges
    │
    ▼
Tests now cover real-world distribution
```

---

## Design Principles for Agent-Native Monitoring

### Principle 1: Everything is Machine-Readable

No monitoring output should require human interpretation to be actionable. Every finding must be structured enough that another agent can:
1. Understand the problem
2. Locate the relevant code
3. Understand what "fixed" looks like
4. Verify the fix worked

### Principle 2: Verification is Continuous, Not Event-Driven

Don't wait for a deploy, a PR, or a cron job. Verify continuously. The cost of an agent checking one thing is negligible. The cost of a bug living in production for 2 days is not.

### Principle 3: Randomized Probing Over Exhaustive Checking

Exhaustive checking is expensive and creates alert fatigue. Random probing is cheap, covers everything over time, and catches issues that fixed schedules miss (because bugs don't follow schedules).

### Principle 4: Self-Referential — The System Audits Itself

The auditor doesn't just check the pipeline's output. It checks:
- Its own findings (are they still valid? was the fix applied?)
- Its own coverage (which dimensions haven't been probed recently?)
- Its own accuracy (did a finding lead to a real fix, or was it a false positive?)

### Principle 5: Evidence Over Assertion

Never say "field X is missing." Say "field X is missing. Here's the file that should produce it (processor/handler.py:310), here's the consumer that expects it (finalizer/handler.py:402), here's the live output proving it's absent (curl command + result), and here's a test that would catch this (test code)."

### Principle 6: Deduplication and Decay

Same finding shouldn't fire repeatedly. Findings have a TTL — if not addressed in N days, they escalate. If the underlying condition changes (code was updated), re-verify before re-reporting.

### Principle 7: The Audit Trail IS the Documentation

The history of findings, fixes, and verifications becomes a living record of system health. It replaces the need for manually-maintained "known issues" lists. `git log --grep` + audit findings = complete system knowledge.

---

## What This Looks Like for TAO Pipeline (POC Scope)

### Phase A: Inline Post-Conditions (Finalizer self-check)
- Verify own output before declaring success
- 20 lines, same Lambda, zero additional cost

### Phase B: Auditor Lambda (hourly, randomized)
- Picks 1-2 dimensions per run
- Outputs `/data/audit_report.json`
- Stores findings in DynamoDB `AUDIT_FINDING#{id}`
- Cost: ~$0 (free tier)

### Phase C: Commit History Analyzer
- Runs on-demand or daily
- Parses git log for orphaned intentions, incomplete refactors
- Cross-references with requirements traceability
- Outputs structured findings

### Phase D: Live Data → Test Fixture Pipeline
- Samples production data weekly
- Computes statistical profiles
- Compares to test fixture ranges
- Auto-generates edge case fixtures

### Phase E: Human-Agent Collaboration Loop
- Agent reads findings queue
- For auto-fixable issues (additive, safe): fix + test + commit + propose PR
- For complex issues: research + plan + propose options
- Human reviews: approves PRs, triages findings, redirects priorities
- Human decides system evolution based on patterns agents surface
- The audit report + HTML dashboard = the collaboration surface

---

## Open Questions

1. **How do we parse natural language requirements into machine-verifiable assertions?**
   - Option A: LLM extracts assertions at design time, stores as structured data
   - Option B: Requirements are written in a semi-structured format from the start
   - Option C: Hybrid — natural language with embedded `VERIFY:` blocks

2. **How do we prevent the auditor from becoming stale itself?**
   - The auditor's checks are code. They drift too.
   - Answer: The auditor audits its own checks against the current codebase.

3. **What's the right granularity for findings?**
   - Too fine: "field X is type float not int" → noise
   - Too coarse: "site is broken" → not actionable
   - Sweet spot: one finding = one PR-sized fix

4. **How do we handle intentional deviations?**
   - Some requirements are descoped. The auditor shouldn't keep flagging them.
   - Answer: Explicit `DESCOPED` annotations in requirements, or a suppression list.

---

## Relationship to Industry Thinking

### What others are doing:

- **Elastic**: Self-healing CI/CD — agents fix build failures automatically (reactive, not proactive)
- **Replit**: Autonomous testing agents that verify output after generation (close to our Phase A)
- **Factory AI**: "Many tasks are easier to verify than to solve" — verification as the moat
- **Stanford research**: Clean codebases get 40% AI productivity boost; messy ones get 0%
- **arxiv 2603.20300**: "Agent interfaces" paper — software should expose explicit contracts for machine invocation
- **arxiv 2604.20436**: Machine-readable requirements reduce implementation drift
- **Zero Drift Engineering** (Zencoder): "AI output must be consistent and verifiable by default"

### Where we go further:

Most of the industry is focused on **generation-time verification** (check the code before it ships). We're proposing **continuous runtime conformance** — the system perpetually verifies itself against its own specification, even after deployment, even as the specification evolves.

The closest analog is **infrastructure drift detection** (Terraform plan vs actual state). We're applying the same concept to **semantic drift** — the gap between what the system is supposed to do (requirements) and what it actually does (live output).

### The key insight from the research:

> "The fundamental unit of software shifts from *feature* to *capability*."
> — Wang et al., "Rethinking Software Design in the Age of AI-Native Systems"

For monitoring, this means: the fundamental unit of verification shifts from *test* to *contract*. A test checks one path. A contract defines what's true at a boundary. Contracts can be verified continuously, against live data, by agents.

---

## Next Steps

1. Implement Phase A (inline post-conditions) — immediate
2. Design the Auditor Lambda schema (findings format, dedup strategy)
3. Build the requirements parser (extract SHALL statements → verifiable assertions)
4. Build the commit history analyzer (orphaned intentions, incomplete refactors)
5. Wire findings to `/data/audit_report.json` (agent-consumable)
6. Eventually: agent picks up findings and proposes fixes
