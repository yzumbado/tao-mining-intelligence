# Agent Plan Execution: Research & System Proposal

> **Status**: PROPOSAL (awaiting validation via tiny experiments)
> **Created**: 2026-05-18
> **Sources**: OpenSearch Agentic SDLC (2026), Loadsys Verification Practice (2026), Reflexion Pattern (Shinn et al. 2023), Agentic Engineering Playbook (vibecoding.app 2026), Kerno Multi-Agent Validation Gates (2026)

---

## Part 1: Research Findings

### Key Patterns from Industry (2024-2026)

#### 1. Harness-First Verification (OpenSearch)

**Pattern**: Each agent runs inside a verification loop ("harness") that validates output before accepting it. The harness encodes quality standards; the agent generates output that the harness validates.

**Key insight**: "Trust must be a system property — a set of invariants the system enforces — not a human judgment that doesn't scale."

**Forms of harness**:
- Deduplication checks (knowledge bases)
- Live integration testing (development)
- Benchmarks (performance)
- Human approval gates (operations)

**Applicable to us**: Our tests (180 passing) ARE a harness. But we don't have a harness for "did the agent complete the spec?" — only "does the code work?"

#### 2. Spec-Driven Verification (Loadsys/Brunel)

**Pattern**: After an agent reports "complete," a separate verification pass compares output against the original specification item by item.

**Key finding**: "Structured verification consistently found 30-40% of the specification unimplemented after the agent reported 'complete.' Not broken code. Missing code."

**Verification check anatomy**:
1. A specific item to verify (concrete, yes/no)
2. Expected evidence (what you'd see in code if implemented)
3. Pass/fail with actual findings

**Iteration pattern**: 5-6 verification passes to reach 100% completion. This is consistent and plannable.

**Applicable to us**: Our plans have acceptance criteria but no structured verification checks. An agent could report "done" while missing 30% of the spec.

#### 3. Reflexion Pattern (Academic + Industry)

**Pattern**: Agent generates output → critiques its own output → revises based on critique → repeats until quality threshold met.

**Evidence**: +11% accuracy on coding tasks, +41% on decision-making, +20% on reasoning (Shinn et al. 2023).

**Key design rule**: "Never let the agent write its own quality gates." The evaluation criteria must be frozen before the agent proposes changes. (OpenSearch Nitro lesson)

**Applicable to us**: Our plans don't tell agents to self-critique. They execute linearly. Adding explicit reflection points after each task would catch errors earlier.

#### 4. Plan → Execute → Verify → Ship (Agentic Engineering)

**Pattern**: Structured loop where:
- **Plan**: Define goal, acceptance criteria, risk limits
- **Execute**: Agent generates code/docs/tests
- **Verify**: CI, tests, security checks, human review
- **Ship**: Merge with audit trail

**4-Layer Guardrail Stack**:
1. Scope guardrails (target files, non-goals, allowed dependencies)
2. Code quality guardrails (lint, test, type check)
3. Policy guardrails (no secrets, no unsafe deps, no main-branch push)
4. Human decision guardrails (architecture, risk acceptance, release timing)

**Applicable to us**: We have layers 2 and 4. We're missing layer 1 (scope guardrails in the plan) and layer 3 (policy checks).

#### 5. Disposable Sub-agents + State on Disk (OpenSearch Nitro)

**Pattern**: "Protect the context window with disposable subagents, and keep the real state on disk."

**Key insight**: Long-running agent sessions accumulate context drift. Use focused sub-agents for specific tasks, each writing results to disk. The coordinator's context stays manageable.

**Applicable to us**: This is exactly our model — main session coordinates, sub-agents execute. But we need the "state on disk" part: agents must write their progress to files that the next agent can read.

---

### What's Proven vs Theoretical

| Pattern | Evidence Level | Source |
|---------|---------------|--------|
| Verification finds 30-40% gaps | Empirical (real project) | Loadsys |
| 5-6 passes to 100% completion | Empirical (consistent across projects) | Loadsys |
| Reflexion +11% on coding tasks | Academic (controlled study) | Shinn et al. |
| Harness-first catches class of bugs | Empirical (OpenSearch production) | OpenSearch |
| Agents miss integration points consistently | Empirical (pattern across projects) | Loadsys, OpenSearch |
| Context drift in long sessions | Empirical (OpenSearch Nitro) | OpenSearch |

---

## Part 2: Proposed System — Structured Agent Plan Format

### Design Principles

1. **Plans are executable specifications** — not prose descriptions, but structured data an agent follows
2. **Verification is built into the plan** — not a separate step after "done"
3. **State lives on disk** — agents write progress to files; next agent reads them
4. **Reflection points are explicit** — the plan tells the agent WHEN to stop and assess
5. **The plan generates more plan** — agents are instructed to create sub-tasks and update docs

### The Task Lifecycle

```
┌─────────────────────────────────────────────────────────────┐
│                    TASK LIFECYCLE                             │
├─────────────────────────────────────────────────────────────┤
│                                                              │
│  1. RESEARCH                                                 │
│  │  Read relevant code, docs, prior decisions                │
│  │  Document findings in task file                           │
│  │  ► CHECKPOINT: "Do I have enough context to proceed?"     │
│  │  ► UPDATE: Add findings to task, flag unknowns            │
│  ▼                                                           │
│  2. PLAN                                                     │
│  │  Break work into sub-tasks with acceptance criteria       │
│  │  Define verification checks (what "done" looks like)      │
│  │  Identify risks and non-goals                             │
│  │  ► CHECKPOINT: "Does plan align with project decisions?"  │
│  │  ► UPDATE: Write plan to task file for next agent         │
│  ▼                                                           │
│  3. IMPLEMENT                                                │
│  │  Execute sub-tasks in order                               │
│  │  After EACH sub-task:                                     │
│  │    ► VERIFY: Run tests, check acceptance criteria         │
│  │    ► REFLECT: "Did this change what I expected?"          │
│  │    ► UPDATE: Mark sub-task done, note any deviations      │
│  ▼                                                           │
│  4. VERIFY                                                   │
│  │  Run ALL verification checks from step 2                  │
│  │  Compare output against spec item-by-item                 │
│  │  ► If gaps found: create fix tasks, return to step 3      │
│  │  ► If clean: proceed to step 5                            │
│  ▼                                                           │
│  5. DOCUMENT & HANDOFF                                       │
│     Update architecture docs if data flow changed            │
│     Update decisions doc if new decision made                │
│     Update metrics reference if metric added/changed         │
│     Commit with structured message                           │
│     ► FINAL CHECK: "Can the next agent understand what I     │
│       did without asking questions?"                         │
│                                                              │
└─────────────────────────────────────────────────────────────┘
```

### Task File Format

Each task gets a structured file that serves as both instruction AND state:

```markdown
# Task: [Title]

## Status: RESEARCH | PLANNING | IMPLEMENTING | VERIFYING | COMPLETE

## Context
- **Why**: [Business reason this task exists]
- **Depends on**: [What must be true before starting]
- **Blocks**: [What can't start until this is done]
- **Decisions to respect**: [Links to relevant DECISION: blocks in code]

## Research Findings
_(Filled by agent during RESEARCH phase)_
- [What was learned]
- [What files are relevant]
- [What prior decisions constrain this work]

## Plan
### Sub-tasks
- [ ] 1. [Sub-task with acceptance criteria]
  - Acceptance: [Concrete, verifiable condition]
  - Files: [Which files will be modified]
  - Non-goals: [What NOT to do]
- [ ] 2. [Next sub-task...]

### Verification Checks
_(How to confirm the task is ACTUALLY done — not just "tests pass")_
| # | Check | Expected Evidence | Pass/Fail | Findings |
|---|-------|-------------------|-----------|----------|
| 1 | [Specific thing to verify] | [What you'd see in code] | | |
| 2 | ... | ... | | |

### Risks & Mitigations
- Risk: [What could go wrong]
  Mitigation: [How to handle it]

## Execution Log
_(Filled by agent during IMPLEMENTING phase)_
- [Timestamp] Sub-task 1: [outcome, any deviations]
- [Timestamp] Sub-task 2: [outcome]
- [Timestamp] REFLECTION: [What I noticed, what surprised me]

## Verification Results
_(Filled by agent during VERIFYING phase)_
- Pass 1: [X/Y checks passed, gaps found: ...]
- Pass 2: [X/Y checks passed, remaining gaps: ...]

## Handoff Notes
_(Filled by agent during DOCUMENT phase)_
- Files modified: [list]
- Docs updated: [list]
- Decisions made: [list with rationale]
- Open questions for human: [if any]
```

### Checkpoint Prompts

At each checkpoint, the agent asks itself these questions:

**After RESEARCH**:
- Do I understand WHY this task exists (not just WHAT to do)?
- Have I read the relevant DECISION: blocks in the code?
- Are there unknowns that would change my approach?
- Should I ask the human before proceeding?

**After PLAN**:
- Does my plan contradict any existing architecture decisions?
- Are my verification checks concrete enough for a yes/no answer?
- Have I defined non-goals (what NOT to do)?
- Can another agent read this plan and execute it without me?

**After each sub-task (IMPLEMENT)**:
- Did the tests pass?
- Did this change produce the effect I expected?
- Did I accidentally modify something outside my scope?
- Should I update the plan based on what I learned?

**After VERIFY**:
- Did I check every item, or did I skip some?
- For items that failed: is the fix clear, or do I need to research more?
- Am I at 100%, or do I need another pass?

**After DOCUMENT**:
- Can the next agent understand what I did from the files alone?
- Did I update all affected docs (architecture, decisions, metrics)?
- Is my commit message structured per the project standard?

---

## Part 3: Validation Experiment

### How to Prove This System Works

**Experiment**: Execute the next 3 planned features using two approaches:
1. **Control**: Fresh agent with normal task description (current approach)
2. **Treatment**: Fresh agent with structured task file (proposed system)

**The 3 features** (from our priority list):
1. Fix HTML site generation (Finalizer template upload)
2. Add SNS alerting on pipeline health
3. Build Staking Intelligence module

**What we measure**:

| Metric | How to Measure | Better = |
|--------|---------------|----------|
| Completion rate (first pass) | Verification checks passed / total checks | Higher |
| Iterations to 100% | How many passes until all checks pass | Fewer |
| Context reads before first action | Count file-read tool calls before first write | Fewer |
| Decision contradictions | Did agent violate a documented decision? | Zero |
| Doc staleness after task | Are affected docs still accurate? | Yes |
| Rework in next session | Does next session undo or redo anything? | Zero |

### Experiment Protocol

**For each feature, run BOTH approaches**:

**Control (current approach)**:
1. Give agent the task description from our todo list
2. Let it read whatever it wants
3. Let it implement however it wants
4. After "done": run verification checks manually
5. Record metrics

**Treatment (structured plan)**:
1. Write the structured task file (research, plan, verification checks)
2. Give agent the task file
3. Agent follows the lifecycle (research → plan → implement → verify → document)
4. After "done": compare verification results
5. Record metrics

**Comparison**:
- Same feature, same codebase state, same model
- Different: the instructions and structure given to the agent
- We can run control first, revert, then run treatment (or vice versa)

### Practical Simplification

Running both approaches on all 3 features is expensive (6 agent sessions). Instead:

1. **Feature 1 (HTML site fix)**: Run with TREATMENT only (it's small, good for testing the format)
2. **Feature 2 (SNS alerting)**: Run with CONTROL (normal task), then measure gaps
3. **Feature 3 (Staking Intelligence)**: Run with TREATMENT (it's complex, biggest payoff)

Compare Feature 2 (control) vs Feature 3 (treatment) on the metrics above. Feature 1 is the pilot to debug the format itself.

---

## Part 4: What to Incorporate Into Our Plan Format

Based on research, these additions to our current plan format:

### Must-Have (High evidence, low effort)

1. **Verification checks table** — Concrete yes/no items with expected evidence. Prevents the "30-40% missing" problem.

2. **Explicit reflection points** — "Stop and assess" after research, after each sub-task, after implementation. Prevents linear execution without self-correction.

3. **Non-goals section** — What the agent should NOT do. Prevents scope creep and "creative drift."

4. **State on disk** — Agent writes progress to the task file as it works. Next agent reads it. Prevents context loss between sessions.

5. **Doc update mandate** — Every task ends with "update affected docs." Prevents staleness.

### Should-Have (Medium evidence, medium effort)

6. **Scope guardrails** — Explicit list of files the agent may modify. Prevents surprise edits.

7. **Decision references** — Link to relevant DECISION: blocks. Prevents contradictions.

8. **Expected iteration count** — "This will likely take 2-3 passes." Sets realistic expectations.

### Nice-to-Have (Theoretical, validate first)

9. **Separate verification agent** — A different agent checks the implementing agent's work. High overhead, unclear if needed for our scale.

10. **Automated check generation from spec** — Generate verification checks programmatically. Only valuable at 50+ checks per feature.

---

## Part 5: Immediate Next Steps

1. **Write structured task file for Feature 1** (HTML site fix) using the proposed format
2. **Launch agent with the structured task file** — observe behavior
3. **Measure**: Did the agent follow checkpoints? Did it self-correct? Did it update docs?
4. **Refine format** based on what worked and what was ignored
5. **Apply refined format to Feature 3** (Staking Intelligence) — the real test

---

## References

- OpenSearch Agentic SDLC (2026): https://opensearch.org/blog/harness-first-agentic-sdlc-how-opensearch-builds-software-using-its-own-search-engine/
- Loadsys Verification Practice (2026): https://www.loadsys.com/blog/agentic-context-engineering-verification-practice/
- Agentic Engineering Playbook (2026): https://vibecoding.app/blog/agentic-engineering-for-software-teams
- Reflexion (Shinn et al. 2023): https://arxiv.org/abs/2303.11366
- Kerno Validation Gates (2026): https://www.kerno.io/blog/multi-agent-validation-gates-for-agentic-coding
- Andrew Ng on Reflection as key agentic pattern: https://huggingface.co/blog/Kseniase/reflection
