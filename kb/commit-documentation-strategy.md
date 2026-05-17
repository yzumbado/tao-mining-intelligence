# Recommendation: Commit Documentation Strategy for All Projects

## Context

During the TAO Mining Intelligence deployment (2026-05-17), we discovered that
rich commit messages serve as a **searchable knowledge base** for future agents.
When an agent reads `git log`, it should be able to reconstruct not just *what*
changed, but *why*, *what was tried and failed*, and *when to revisit*.

This saved us from repeating 3 dead-end approaches during a single deployment
session (mkdir /dev/shm, full module mock, wrong platform type).

## Proposal for Global Steering

Add the following to the global git commit standards (e.g., `amazon-builder-git.md`
or a new `commit-documentation.md` with `inclusion: always`):

---

### Commit Documentation for Fixes and Decisions

For any commit that fixes a bug, resolves a deployment issue, or makes an
architectural decision, use this extended structure:

```
<type>(<scope>): <what changed>

Diagnosis: How the problem was discovered and what symptoms were observed.

Root cause: The actual underlying issue (not the symptom).

[Attempted fix N: What was tried and why it failed.]

Fix: What was done and why this approach was chosen over alternatives.

Verification: How the fix was validated (commands, test results).

[Decision: Why this approach over alternatives — trade-offs considered.]

[When to revisit: Conditions under which this fix should be reconsidered.]
```

### Rules

- **Document failed attempts** — saves future agents from repeating dead ends
- **Include the "why not"** — not just what you did, but what you rejected
- **Reference specific file:line** — makes it greppable
- **State verification commands** — anyone should be able to reproduce
- **Add "When to revisit"** for workarounds — prevents permanent tech debt
- **Remove dead code** — document failed approaches in commits, not in source

### Why This Matters for Multi-Agent Workflows

1. An agent reading `git log` reconstructs full decision context without asking
2. Failed approaches are documented once instead of rediscovered repeatedly
3. The commit history becomes a knowledge base searchable with `git log --grep`
4. Future refactors can check if workaround conditions still apply
5. Coordination agents can extract patterns across projects

---

## Adoption Path

1. Add to global steering as a recommended practice
2. Each project's coding-standards.md should reference it
3. Agents should follow this for any fix/decision commit (not for trivial changes)
4. Simple feature additions can use standard conventional commits format

## Evidence

See these commits in tao-mining-intelligence for examples:
- `fix(cdk): Set Lambda architecture to ARM64 and add HOME=/tmp`
- `fix(lambda): Patch bittensor multiprocessing.Queue for Lambda`
- `fix: Resolve Docker import path mismatch blocking deployment`

## Enforcement Gap (For Coordination Agent)

**Problem observed**: Even after establishing the commit documentation strategy
as a work mechanic, the very next documentation commit (`docs: Sync all
documentation...`) was initially written WITHOUT the required structure. It
took a human review ("does the commit message follow our rules?") to catch it.

**Root cause**: The strategy is documented in steering files, but there's no
automated enforcement. An agent under time pressure defaults to shorter
messages unless actively reminded.

**Recommendations for the coordination agent**:

1. **Pre-commit hook concept**: Before any `git commit`, the agent should
   self-check: "Does this commit message follow the Diagnosis/Root cause/Fix
   structure?" For simple feature additions, conventional commits suffice.
   For ANY fix, decision, or refactor — the full structure is mandatory.

2. **Post-milestone audit**: After every major milestone (deployment, arch
   change, live validation), run a documentation audit. Use a sub-agent to
   check all docs against current state. This catches drift that accumulates
   across multiple commits.

3. **Commit review as a gate**: Before marking a task complete, re-read the
   commit message as if you're a future agent seeing it for the first time.
   Ask: "Would I understand WHY this was done, WHAT was tried, and WHEN to
   revisit?" If not, amend before moving on.

4. **Pattern detection**: If an agent produces 3+ commits in a row without
   the full structure on fix/decision commits, flag it. The strategy only
   works if it's consistent — one undocumented fix creates a gap in the
   knowledge chain.

5. **Include in agent initialization**: When a new agent session starts on
   any coding project, the steering should include: "All fix and decision
   commits MUST follow the Diagnosis → Root cause → Fix → Verification
   structure. See kb/commit-documentation-strategy.md."

