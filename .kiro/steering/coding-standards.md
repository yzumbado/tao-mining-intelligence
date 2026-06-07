---
inclusion: always
---

# TAO Mining Intelligence Pipeline — Coding Standards

## Development Workflow

### Session Start (Agent Boot-Up)

When starting a new session on this project:

1. **Read handoff.md** (auto-loaded) — understand current stage, pending tasks, dead ends
2. **Check production health**: `curl -s https://dkfh19zkgqq18.cloudfront.net/data/rankings.json | python3 -c "import json,sys; d=json.load(sys.stdin); print(f'{len(d)} subnets, max APY {max(r[\"real_apy_percent\"] for r in d):.0f}%')"`
3. **Check git status**: `git -P log --oneline -5` — confirm you're on main, up to date
4. **Ask the user what they want to work on** — don't assume from pending tasks

### Session Close (Before Ending)

Before ending a session:

1. **Run tests**: `pytest tests/ -q` — must pass
2. **Push all commits**: `git push` — nothing left local
3. **Update handoff.md**: session findings, lessons learned, pending tasks
4. **Verify docs match code**: if you changed a metric or architecture, update the relevant docs
5. **Commit the handoff update** and push

### Feature Development (When Building)

When building a new feature or fixing a bug, follow this order:

1. **POC against live chain** (5 min) — verify your assumptions about field values, API behavior, or formula correctness BEFORE writing production code
2. **Write property test** — define what "correct" means (bounds, monotonicity, edge cases)
3. **Implement** — write the minimum code to pass the test
4. **Run all tests** — `pytest tests/ -q` (205 must pass)
5. **Cross-validate** — `python scripts/validate_all_metrics.py` (compare against live chain)
6. **Update docs** — if you changed a metric, run `python scripts/generate_metrics_reference.py`
7. **Commit** — following the structured commit format below
8. **Deploy** — `./scripts/deploy.sh` (runs tests, deploys, validates post-deploy)
9. **Verify production** — check live output at `https://dkfh19zkgqq18.cloudfront.net/data/rankings.json`

**Key rule**: Steps 1 and 5 are what catch value bugs. Tests (step 4) catch structural bugs. Both are mandatory.

**Deploy prerequisites** (will fail without these):
- Colima running: `colima start`
- AWS profile `tao` in `~/.aws/credentials` (account 651484323929)
- Python 3.12 venv active: `source .venv/bin/activate`
- Node.js/npx available for CDK

**Formula deploys use `--skip-validation`**: When deploying a formula fix, the validation gate (which compares live output vs chain) will always fail pre-deploy because the live output IS the bug. Use `./scripts/deploy.sh --skip-validation` and verify manually post-deploy.

## General Principles

- Python 3.12, type hints on all function signatures
- Pydantic v2 for data models (defined in `lambda/src/models/`)
- Every function that can fail returns a result type or raises a specific exception — no silent failures
- All code must be testable without AWS credentials (dependency injection, moto for tests)

## DynamoDB Rules

- NEVER use Python `float` in DynamoDB writes — always convert to `Decimal` using `_float_to_decimal()` from `state.state_manager`
- ALWAYS use conditional expressions for state transitions (prevent race conditions)
- PK/SK patterns: `SUBNET#{netuid}`, `CONFIG`, `CYCLE#{cycle_id}`, `HOTKEY#{ss58}`, `RANKING`, `BRIEFING`

## Metrics Engine Rules

- NEVER hardcode threshold values — always read from configurable thresholds (`get_thresholds()`)
- Emission values from metagraph are PER TEMPO — multiply by `(7200 / tempo)` for daily
- Only average across EARNING miners (emission > 0) for ROI calculations on WTA subnets
- All metric functions are PURE (no side effects, no AWS calls) — they take data in and return data out
- Registration costs from chain are in RAO — divide by 1e9 for TAO

## Instrumentation Rules

- EVERY significant operation must be wrapped in `instrument(component, operation, netuid)`
- trace_id must be propagated through SQS messages
- NEVER log full coldkey addresses — truncate to 12 chars
- NEVER log Parameter Store values (API keys)
- Error messages truncated to 500 chars in logs

## Testing Rules

- TDD: write property test FIRST, then implement
- All property tests use Hypothesis with minimum 100 examples
- Unit tests use moto for AWS mocking — no real AWS calls
- Every algorithm has a corresponding property test in `tests/properties/`
- Test file naming: `test_{module_name}.py`

### Import Path Discipline (Lesson Learned)

- **NEVER use `sys.path.insert()` in individual test files** — centralize in `conftest.py`
- Tests MUST import modules using the SAME path that the runtime uses (Docker container)
- If the Dockerfile does `COPY src/ ${LAMBDA_TASK_ROOT}/src/`, then imports must be `from src.X`
- If the Dockerfile does `COPY src/ ${LAMBDA_TASK_ROOT}/`, then imports must be `from X` (no prefix)
- **The CDK `cmd=` value MUST match the Dockerfile COPY layout** — test this explicitly
- Any script in `scripts/` that imports from `lambda/src` must be smoke-tested in CI

### Tests Must Not Lie

- A test that passes with a different import path than production is **lying**
- If tests add both `lambda/` and `lambda/src/` to sys.path, they mask import resolution bugs
- **Rule**: The test environment's module resolution must be identical to the container's
- After any Dockerfile or import refactor, run a Docker build + import smoke test:
  ```bash
  docker build -t test-imports lambda/ && \
  docker run --rm test-imports python -c "from src.processor.handler import handle; print('OK')"
  ```

### What Tests Must Cover Beyond Logic

- **Entry point resolution**: Can Lambda find the handler at the CMD path?
- **Internal import chains**: Does handler → storage → config resolve without sys.path hacks?
- **SQS message format**: Does the message the producer sends match what the consumer parses?
- **Field alignment**: Do mock snapshots in tests use the exact same field names as real collectors?

## Security Rules

- All dependencies pinned to exact versions in `lambda/requirements.txt`
- No secrets in Lambda environment variables — use Parameter Store
- S3 data bucket: NEVER grant public access
- IAM: no wildcard actions, no delete permissions on data

## File Organization

```
lambda/src/
├── config.py              # PIPELINE_ENV switching, singleton config
├── instrumentation.py     # Tracing, structured logging
├── validation.py          # Data validation at ingestion
├── circuit_breaker.py     # Circuit breaker + timeout utilities
├── thresholds.py          # Configurable parameters with defaults
├── sanity_check.py        # Post-processing data quality checks
├── lambda_patch.py        # Bittensor multiprocessing.Queue patch for Lambda
├── models/
│   ├── enums.py           # All enumerations
│   └── schemas.py         # All Pydantic data models
├── state/
│   └── state_manager.py   # DynamoDB FSM + config + hotkey tracking
├── storage/
│   └── storage_layer.py   # S3/local filesystem with compression
├── discovery/
│   └── handler.py         # Discovery Lambda (hourly safety net)
├── subnet_collector/
│   └── handler.py         # SubnetCollector Lambda (one subnet per invocation)
├── processor/
│   ├── metrics.py         # Pure computation (all algorithms)
│   └── handler.py         # Lambda handler (wires components)
├── finalizer/
│   └── handler.py         # Lambda handler (briefing + ranking + site)
├── site_generator/
│   └── generator.py       # Jinja2 HTML generation
├── researcher/
│   └── handler.py         # Stage 2: subnet repo research
└── market_observer/
    └── handler.py         # High-frequency cache + time-series (10-min cadence)
```

## Conventions

- Dates: ISO format `YYYY-MM-DD` (string)
- Timestamps: ISO format with timezone `2026-05-15T00:05:23+00:00`
- TAO amounts: float, never exceeds 21,000,000
- Percentages: float in [0.0, 1.0]
- Block numbers: positive integers
- Hotkeys: SS58 format strings (start with "5")

## Commit Documentation Strategy

Commits are not just history — they are **guidance for future agents** navigating the codebase. Every fix or decision commit must follow this structure:

### Structure

```
<type>(<scope>): <what changed>

Diagnosis: How the problem was discovered and what symptoms were observed.

Root cause: The actual underlying issue (not the symptom).

[Attempted fix N: What was tried and why it failed.] (include all failed attempts)

Fix: What was done and why this approach was chosen over alternatives.

Verification: How the fix was validated (commands, test results).

[Decision: Why this approach over alternatives — trade-offs considered.]

[When to revisit: Conditions under which this fix should be reconsidered.]
```

### Rules

- **Document failed attempts** — saves future agents from repeating dead ends
- **Include the "why not" for alternatives** — not just what you did, but what you rejected
- **Reference specific file:line when relevant** — makes it greppable
- **State verification commands** — anyone should be able to reproduce validation
- **Add "When to revisit"** for workarounds — so they don't become permanent tech debt
- **Remove dead code** — if a fix attempt didn't work, don't leave it in the codebase; document it in the commit message instead

### Why This Matters

- An agent reading `git log` can reconstruct the full decision context
- Failed approaches are documented once (in commits) instead of rediscovered repeatedly
- The commit history becomes a searchable knowledge base of "what we tried and learned"
- Future refactors can check if the conditions that forced a workaround still apply
