# Proof 2: Commit History Analysis

**Date**: 2026-05-19
**Question**: Can commit history reveal bugs or issues we didn't know about?
**Answer**: Yes. Found 4 orphaned features (code exists, never called), 2 dead code modules, and a pattern of "feat without test" commits that correlates with the bugs we found today.

---

## Findings

### Finding A: 4 Orphaned Features (code exists, never wired into pipeline)

| Feature | Code Location | Status | Impact |
|---------|--------------|--------|--------|
| `rental_profitability` | `metrics.py:681` (full implementation) | Never called in `processor/handler.py` | Dead code — 100 lines of tested logic that produces nothing |
| `entry_barrier` | `schemas.py:407` (model defined) | Never computed anywhere | Schema placeholder — no algorithm exists |
| `seven_day_trend` | `metrics.py:1208` (parameter accepted) | Never passed data (always `None`) | Feature stub — emission trend only does day-over-day |
| `top_movers` | `finalizer/handler.py:287` | Hardcoded as `[]` | Briefing field that's always empty |

**How the auditor would detect this**: For each function in `metrics.py`, check if it's called from `handler.py`. For each field in output schemas, check if it's ever populated with non-default values.

### Finding B: "feat without test" pattern correlates with today's bugs

Commits that changed `lambda/src/` without touching `tests/`:

| Commit | What it did | Bug it introduced |
|--------|-------------|-------------------|
| `4af0b9b` | Added HTML site generation + staking | **Empty badges** (wired rankings to template without enrichment) |
| `f95fd0b` | Added llms.txt + metadata.json | **source_block=0** (assumed field existed in derived metrics) |
| `9676603` | Fixed ROI=0 | Unknown (no test added for the fix) |
| `9a3c313` | Processor invokes Aggregator | Unknown (no test for invocation) |
| `58a86a5` | SubnetCollector + self-scheduling | Unknown (no test for scheduling) |

**Pattern**: 5/10 "feat without test" commits are in the AD18 refactor wave. The velocity of shipping AD18 (7 commits in one day) outpaced test coverage. 2 of today's 3 bugs trace directly to these commits.

**How the auditor would detect this**: Flag any commit that modifies `lambda/src/**/*.py` without a corresponding change in `tests/`. Severity: "info" for docs-only changes, "warning" for logic changes.

### Finding C: 2 Dead Code Modules

| Module | Status | Evidence |
|--------|--------|----------|
| `lambda/src/orchestrator/handler.py` | Never imported | Marked "legacy" in handoff, but still in container image |
| `lambda/src/collector/handler.py` | Never imported | Marked "legacy" in handoff, but still in container image |

**Impact**: These add ~200 lines to the Docker image that serve no purpose. Low risk but adds confusion for any agent reading the codebase.

**How the auditor would detect this**: For each module in `lambda/src/*/handler.py`, check if it's imported anywhere outside its own directory. If not, flag as dead code.

### Finding D: Design Doc → Code Drift (3 metrics specified but not implemented)

The design doc's "Derived Metrics Schema" specifies these fields that don't exist in production output:

| Field | Design Doc Says | Reality |
|-------|----------------|---------|
| `rental_profitability` | Full schema with 7 sub-fields | Function exists but never called |
| `entry_barrier` | Schema with score, cost, hardware tier | Model defined, no computation |
| `seven_day_trend` | Part of emission_trend | Parameter accepted but never passed data |

**How the auditor would detect this**: Parse the design doc's JSON schema examples, extract field names, verify each exists in live output with non-null values.

---

## Patterns That Predict Bugs

Based on this analysis, these commit patterns correlate with bugs:

| Pattern | Signal Strength | Example |
|---------|----------------|---------|
| `feat` commit without test file change | **Strong** | 2/3 of today's bugs came from these |
| Large commit (>5 files) with mixed concerns | **Medium** | `4af0b9b` (3 features in 1 commit) introduced a bug |
| Commit mentions "non-critical" or "best-effort" | **Medium** | HTML generation wrapped in try/except hid the empty badges |
| Feature added to schema but never computed | **Weak** | Not a bug per se, but indicates spec↔code drift |
| "Legacy" / "reference" code kept in tree | **Weak** | Confusion risk, not a runtime bug |

---

## What This Proves

1. **Git history contains strong signal** — the "feat without test" pattern directly predicted 2/3 of today's bugs. An auditor checking this pattern on May 17 (when the commits landed) would have flagged them immediately.

2. **Orphaned features are detectable mechanically** — "function defined but never called from handler" is a simple grep. No LLM needed.

3. **Velocity correlates with gaps** — the AD18 refactor (7 commits in one day) produced the most untested code. The auditor could flag "high-velocity days" for extra scrutiny.

4. **Dead code is trivially detectable** — import analysis finds modules that exist but are never referenced.

5. **Design doc drift is real and measurable** — 3 metrics in the design doc don't exist in production. This is exactly what Dimension 2 (spec↔code) would catch.

---

## New Design Rules for the Auditor

| Rule | Derived from |
|------|-------------|
| Flag `feat`/`fix` commits that don't touch test files | Pattern B: 2/3 bugs came from these |
| For each function in metrics.py, verify it's called from a handler | Finding A: 4 orphaned features |
| For each module in src/*/handler.py, verify it's imported somewhere | Finding C: 2 dead modules |
| Flag "high-velocity days" (>3 commits) for extra audit scrutiny | Pattern: AD18 wave produced most gaps |
| Parse design doc schemas, verify fields exist in live output | Finding D: 3 specified-but-missing metrics |
