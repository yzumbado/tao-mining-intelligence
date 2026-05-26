# 5. Quality & Testing

## Test Strategy

### Layers

| Layer | Count | What It Validates | Tools |
|-------|-------|-------------------|-------|
| Property tests | 96 | Algorithm invariants (bounds, monotonicity, edge cases) | Hypothesis (200+ examples each) |
| Unit tests | 90 | Handler behavior with mocked AWS | moto, pytest |
| Contract tests | 4 | Processor output consumable by Finalizer (no mocks between) | moto, real handlers |
| Integration (E2E) | 6 | Full pipeline flow with mocked chain | moto |
| CDK tests | 13 | Infrastructure assertions | aws-cdk assertions |
| **Total** | **210** | | |

### Contract Test Pattern (Phase A — implemented)

The most valuable test in the suite. Runs the real Processor, captures its S3 output, and feeds it directly to the real Finalizer. Zero hand-crafted mocks between components.

```
Real Processor → S3 output → Real Finalizer._generate_rankings()
                           → Real Finalizer._generate_staking_rankings()
                           → Real Finalizer._generate_briefing()
```

Catches: field renames, type changes, missing fields, path mismatches.

### Conformance System (Phase A — inline post-conditions)

5 checks run on every Finalizer invocation:
1. Rankings count == metrics count
2. No NaN/None in critical fields
3. Rankings sorted descending
4. Briefing date matches expected
5. At least some subnets have source_block > 0

Logs structured JSON findings. Never blocks pipeline.

## Known Test Limitations (MEDIUM severity)

| # | Issue | Impact |
|---|-------|--------|
| 1 | `conftest.py` adds both `lambda/` and `lambda/src/` to sys.path | Property tests use wrong import path (works in tests, would fail in Docker) |
| 2 | Processor test only checks structure, not values | Could write NaN without failing |
| 3 | E2E test seeds data manually (not real Collector output) | Misses Collector→Processor format drift |
| 4 | "Idempotency" test proves non-idempotency | Misleading name |
| 5 | Taoflow always HEALTHY in tests | Dead code path never exercised |
| 6 | Output contract test hardcodes llms.txt | Could drift from production |

## Lessons Learned (Testing)

1. **206 unit tests passed while 2 CRITICAL contract bugs existed.** Unit tests with hand-crafted mocks can't catch contract drift. The contract smoke test catches what unit tests can't.

2. **Tests that seed data at wrong S3 paths pass silently.** The handler falls back to defaults (0.0) without error. Always verify that test data actually reaches the code path you think you're testing.

3. **"Test the contract, not the unit"** — the boundary between components is where bugs live. A test that runs Producer → Consumer with real data is worth 50 unit tests with mocks.

4. **Property tests catch real bugs** — floating-point issues in slippage, edge cases in Gini, monotonicity violations in deregistration risk. Hypothesis finds inputs humans wouldn't think of.

5. **Live data validates hypotheses** — SN104 investigation proved our score was broken. Validator concentration analysis proved the binary flag was useless. No amount of unit testing would have found these.

## Code Quality Rules

- Type hints on all function signatures
- Pydantic v2 at storage/API boundaries
- Every function that can fail returns a result or raises specific exception
- All dependencies pinned to exact versions
- No secrets in environment variables (Parameter Store)
- Structured logging with trace_id propagation
- `import math` at module top (not inside methods — known violation in 2 places)
