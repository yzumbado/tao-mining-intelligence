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
