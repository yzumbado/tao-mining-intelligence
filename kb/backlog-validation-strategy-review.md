# Backlog: Deep Validation Strategy Review

**Priority**: HIGH
**Trigger**: Output contract bugs found 2026-05-19 (commit 2113d7e)
**Status**: NOT STARTED

## Problem Statement

193 passing tests failed to catch 3 bugs that were visible on the live site for 2 days. The root cause is systemic: **unit tests use idealized mock data that doesn't match production data shapes**, and there are no integration tests that wire real producer output into real consumer input.

## Evidence

| Bug | Tests that should have caught it | Why they didn't |
|-----|----------------------------------|-----------------|
| Empty badges on index.html | test_site_generator.py | Test uses `_make_subnet_summary()` with all fields; production `_generate_rankings()` only produces 8 fields |
| source_block=0 in metadata.json | test_finalizer.py | `_make_derived_metrics()` doesn't include `source_block_number` — matches the bug, not the fix |
| Broken nav link | test_site_generator.py | Tests check HTML content, never verify link targets exist |

## Scope of Review

1. **Audit all test data factories** — compare fields in `_make_*()` helpers against what the real code produces. Flag any field present in test data but absent from production output.

2. **Identify all cross-component data contracts** — every place where one Lambda's output becomes another Lambda's input:
   - SubnetCollector → S3 → Processor (raw snapshot schema)
   - Processor → S3 → Finalizer (derived metrics schema)
   - Processor → DynamoDB → Finalizer (profiles)
   - Finalizer → S3 → CloudFront (site files, JSON endpoints)
   - Finalizer → SiteGenerator (rankings → template)

3. **Define contract test pattern** — establish a reusable pattern where:
   - Producer tests assert output shape matches a shared schema
   - Consumer tests import the SAME shared schema as input
   - No test data factory can add fields that the producer doesn't produce

4. **Evaluate Pydantic model coverage** — the pipeline uses Pydantic for some boundaries but not all. Specifically:
   - Rankings output is a plain dict (no model validation)
   - Derived metrics output is a plain dict (no model validation)
   - Template input is untyped (Jinja2 accepts any dict)

5. **Consider snapshot testing** — capture real production output shapes and assert tests match them.

## Proposed Outcomes

- [ ] Shared output schema definitions (Pydantic or TypedDict) for each cross-component boundary
- [ ] Contract tests that wire real producer output → real consumer input (no mocks at the boundary)
- [ ] Test data factories that are GENERATED from the shared schemas (not hand-written)
- [ ] CI check that fails if a template references a field not in the producer's output schema
- [ ] Document the validation strategy in coding-standards.md

## Related

- Commit `2113d7e`: fix(site): Fix 3 output contract bugs + add contract tests
- Handoff lesson: "180 passing tests can still hide a deployment-blocking bug"
- Handoff lesson: "Tests Must Not Lie"
- `tests/unit/test_output_contracts.py`: Initial contract tests (7 tests, covers the 3 bugs found)
