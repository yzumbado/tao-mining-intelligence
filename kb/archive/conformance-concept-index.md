# Continuous Conformance System — Concept Index

**Created**: 2026-05-19
**Status**: Brainstorming → needs decomposition and proof

---

## Concept Areas

Each area needs its own document with: definition, boundaries, open questions, and a proof exercise we can run before implementing.

| # | Area | Maturity | Doc | Proof Exercise |
|---|------|----------|-----|----------------|
| 1 | Design Principle: Human-Agent Collaboration | ✅ Solid | `design-principle-agent-native-conformance.md` | N/A — this is the "why" |
| 2 | Audit Dimension: Spec ↔ Code Drift | 🟡 Concept only | `TODO` | Parse 5 requirements → verify against live output |
| 3 | Audit Dimension: Code ↔ Output Verification | 🟡 Concept only | `TODO` | Run post-conditions on current Finalizer output |
| 4 | Audit Dimension: Test ↔ Production Shape | 🟡 Concept only | `TODO` | Compare 3 test factories to live data |
| 5 | Audit Dimension: Commit History Analysis | 🟡 Concept only | `TODO` | Analyze last 20 commits for orphaned intentions |
| 6 | Audit Dimension: Live Data → Test Fixtures | 🟡 Concept only | `TODO` | Sample 5 subnets, compare to test value ranges |
| 7 | Findings Schema & Lifecycle | 🔴 Undefined | `TODO` | Define schema, write 3 example findings from today's bugs |
| 8 | Auditor Architecture (Lambda, triggers, cost) | 🔴 Undefined | `TODO` | Estimate cost, define trigger strategy |
| 9 | Collaboration Surface Design | 🟡 Partial | (in main doc) | Mock audit_report.json from today's findings |
| 10 | Auto-Fix Boundaries & Safety | 🔴 Undefined | `TODO` | Define what's safe to auto-fix vs requires human |

---

## What's Still Loose (by category)

### A. Foundational (must define before anything else)

1. **Findings Schema** — What does a "finding" look like? What fields? How does an agent consume it? How does a human triage it? This is the contract between the auditor and everything downstream.

2. **What "correct" means** — How do we represent requirements in a machine-verifiable way? Natural language parsing? Semi-structured format? Inline annotations? This determines whether Dimension 2 (spec↔code) is even feasible without an LLM in the loop.

3. **Collaboration surface** — What does the human see? Is it the existing HTML site with an added "health" page? A separate audit_report.json? Both? How does the human say "ignore this finding" or "this is intentional"?

### B. Architectural (must define before building)

4. **Auditor execution model** — Single Lambda? Multiple specialized Lambdas? How often? Random selection strategy? Cost model?

5. **State management** — Where do findings live? DynamoDB? S3? How do we deduplicate? How do we track "acknowledged" vs "open" vs "fixed"?

6. **Auto-fix boundaries** — What's safe for an agent to fix without human approval? What requires a PR? What requires human decision? Classification criteria.

### C. Per-Dimension Design (can be defined incrementally)

7. **Spec parser** — How to extract verifiable assertions from requirements.md
8. **Output verifier** — What post-conditions to check, where to run them
9. **Test shape comparator** — How to compare test factories to live data
10. **Commit analyzer** — What patterns to look for, how to avoid false positives
11. **Fixture generator** — How to sample, what to save, where to store

---

## Proof Exercises (do BEFORE implementing)

These are cheap experiments we can run in a single session to validate the concept works before building infrastructure.

### Proof 1: "Can we parse requirements into verifiable assertions?"
- Take 5 "SHALL" statements from requirements.md
- Manually extract the assertion (field X must exist in output Y)
- Check against live CloudFront data
- **Question answered**: Is the requirements doc structured enough for automated parsing?

### Proof 2: "Can commit history reveal bugs we didn't know about?"
- Analyze last 30 commits
- Look for: fields mentioned in commit messages that don't appear in all relevant files
- Look for: "TODO" or "propagate" in commits without follow-up
- **Question answered**: Does our commit history actually contain signal, or is it too clean?

### Proof 3: "How different is test data from production data?"
- Fetch live rankings.json
- Compare field-by-field to `_make_rankings()` in test_site_generator.py
- Compute value distributions (min/max/median) for each numeric field
- **Question answered**: How badly are our tests lying about production reality?

### Proof 4: "What would a finding look like for today's bugs?"
- Write 3 structured findings for the bugs we fixed today
- Include all fields we think an agent would need to fix them
- Try to "execute" the finding mentally — could an agent fix it from this info alone?
- **Question answered**: Is our findings schema complete enough?

### Proof 5: "What's safe to auto-fix?"
- Review the 3 bugs we fixed today
- Classify each: could an agent have safely fixed this without human approval?
- Define the criteria that made each safe or unsafe
- **Question answered**: Can we define clear auto-fix boundaries?

---

## Suggested Sequence

```
1. Run Proof 4 first (findings schema)
   → This defines the contract everything else depends on

2. Run Proof 1 (requirements parsing)
   → This tells us if Dimension 2 is feasible without LLM

3. Run Proof 3 (test vs production)
   → Quick win, immediately useful, grounds the concept

4. Run Proof 2 (commit history)
   → Novel, validates the most unique part of the idea

5. Run Proof 5 (auto-fix boundaries)
   → Needed before Phase E, but not before Phase A-B

Then implement:
   Phase A: Inline post-conditions (uses findings from Proof 4)
   Phase B: Auditor Lambda (uses architecture from area 8)
   Phase C+: Per-dimension implementation
```

---

## Documents to Create

| Doc | Purpose | Depends on |
|-----|---------|-----------|
| `conformance-findings-schema.md` | Define the finding data model | Proof 4 |
| `conformance-spec-parser.md` | How to extract assertions from requirements | Proof 1 |
| `conformance-commit-analyzer.md` | Patterns to detect in git history | Proof 2 |
| `conformance-test-grounding.md` | How to compare tests to production | Proof 3 |
| `conformance-auto-fix-policy.md` | What's safe to auto-fix, classification | Proof 5 |
| `conformance-architecture.md` | Lambda design, triggers, cost, state | Proofs 1-5 |
| `conformance-collaboration-surface.md` | What humans see, how they interact | Proof 4 |

---

## Design Rules (derived from proofs)

Lessons learned from running Proofs 3 and 4 on 2026-05-19. These constrain the architecture.

| # | Rule | Evidence | Implication |
|---|------|----------|-------------|
| 1 | Track "last triggered" for every conditional output path | Emission alert threshold (10%) never fired in 2 days — feature was dead | Auditor maintains a registry of conditional paths + last-fire timestamps |
| 2 | Maintain statistical profiles of live numeric fields | Test `competitive_density` values (0.2-0.4) are 3-5x above live max (0.074) | Auditor computes min/max/median per field, flags test fixtures outside live range |
| 3 | Detect when code hardcodes values that exist in config | Finalizer hardcoded `0.10` despite `thresholds.py` having the same value | Auditor scans for literals that duplicate configurable parameters |
| 4 | Operate on live production data, not just code | No static analysis could determine 10% is wrong for Bittensor emissions | Auditor MUST fetch and analyze live outputs — this is runtime verification |
| 5 | Findings separate detection (agent) from decision (human) | Fixing the threshold was 2 lines, but knowing the right value required domain reasoning | Agent says "this never fires, live range is X"; human says "lower to Y" |
| 6 | Cheap probes > exhaustive checks | Proof 3 took 5 min, found a dead feature + a design question | Auditor runs targeted probes, not full scans. Coverage via randomization over time |
| 7 | "Never-fires" detection is highest ROI | Found dead alerts, dead badges, dead density penalty — all from one pattern | Priority check: for each output branch, has it ever produced non-default output? |
