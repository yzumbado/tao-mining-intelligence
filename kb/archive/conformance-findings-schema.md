# Conformance Findings Schema

**Status**: PROOF 4 — derive schema from real examples
**Date**: 2026-05-19

---

## Proof Exercise: 3 Findings From Today's Bugs

These are written as if the Auditor detected them. The goal: could an agent read this and fix the bug without asking questions?

---

### Finding 1: Broken Nav Link

```json
{
  "finding_id": "CF-2026-05-19-001",
  "detected_at": "2026-05-19T06:00:00Z",
  "audit_dimension": "link_integrity",
  "severity": "bug",
  "confidence": "certain",

  "title": "Nav link /briefings/latest.html returns 403 — file does not exist",

  "observation": {
    "what_was_checked": "All href attributes in <nav> element of generated HTML pages",
    "expected": "Every nav href resolves to a file uploaded to the site bucket",
    "actual": "href='/briefings/latest.html' returns HTTP 403 (CloudFront: no such key)",
    "evidence_command": "curl -s -o /dev/null -w '%{http_code}' https://dkfh19zkgqq18.cloudfront.net/briefings/latest.html",
    "evidence_result": "403"
  },

  "diagnosis": {
    "root_cause": "Template base.html uses path '/briefings/latest.html' but _upload_agent_files() uploads to '/briefing.html'",
    "introduced_by": "bec567e (template written against design doc URL scheme) + f95fd0b (upload code chose simpler path)",
    "why_tests_missed_it": "test_site_generator.py checks HTML content but never verifies link targets resolve to uploaded files"
  },

  "location": {
    "file_to_fix": "lambda/templates/base.html",
    "line_hint": "href=\"/briefings/latest.html\"",
    "related_files": ["lambda/src/finalizer/handler.py"]
  },

  "suggested_fix": {
    "action": "replace_string",
    "old_value": "/briefings/latest.html",
    "new_value": "/briefing.html",
    "rationale": "Match the actual upload path used in _upload_agent_files()"
  },

  "verification": {
    "command": "curl -s -o /dev/null -w '%{http_code}' https://dkfh19zkgqq18.cloudfront.net/briefing.html",
    "expected_result": "200",
    "test_to_add": "Verify all nav hrefs exist in UPLOADED_FILES set"
  },

  "classification": {
    "auto_fixable": true,
    "fix_type": "string_replacement",
    "risk": "low",
    "reason_safe": "Additive change to a template, no logic change, existing tests cover rendering"
  }
}
```

---

### Finding 2: source_block_number Not Propagated

```json
{
  "finding_id": "CF-2026-05-19-002",
  "detected_at": "2026-05-19T06:00:00Z",
  "audit_dimension": "field_lineage",
  "severity": "bug",
  "confidence": "certain",

  "title": "source_block is 0 for all 129 subnets in metadata.json — field not propagated through processor",

  "observation": {
    "what_was_checked": "Field lineage: source_block_number from raw snapshot → derived metrics → metadata.json",
    "expected": "metadata.json subnets.{N}.source_block > 0 (chain block number at collection time)",
    "actual": "All 129 entries have source_block: 0",
    "evidence_command": "curl -s https://dkfh19zkgqq18.cloudfront.net/data/metadata.json | python3 -c \"import json,sys; d=json.load(sys.stdin); print(sum(1 for s in d['subnets'].values() if s['source_block']==0))\"",
    "evidence_result": "129"
  },

  "diagnosis": {
    "root_cause": "Processor's _build_derived_output() does not include source_block_number in metadata dict. Finalizer reads meta.get('source_block_number', 0) → always gets default.",
    "introduced_by": "f95fd0b added metadata.json generation assuming derived metrics would mirror raw snapshot metadata. 58a86a5 (processor) never propagated the field.",
    "why_tests_missed_it": "test_finalizer.py's _make_derived_metrics() doesn't include source_block_number either — test matches the bug, not the spec.",
    "field_trace": {
      "origin": {"file": "lambda/src/subnet_collector/handler.py", "line": 126, "writes": "metadata.source_block_number = int(mg.block)"},
      "consumed_internally": {"file": "lambda/src/processor/handler.py", "line": 111, "reads": "snapshot.get('metadata', {}).get('source_block_number', 5000000)"},
      "not_propagated_to": {"file": "lambda/src/processor/handler.py", "function": "_build_derived_output", "missing_field": "source_block_number"},
      "consumer_expects": {"file": "lambda/src/finalizer/handler.py", "line": 402, "reads": "meta.get('source_block_number', 0)"}
    }
  },

  "location": {
    "file_to_fix": "lambda/src/processor/handler.py",
    "function": "_build_derived_output",
    "line_hint": "\"metadata\": {",
    "related_files": ["lambda/src/finalizer/handler.py", "lambda/src/subnet_collector/handler.py"]
  },

  "suggested_fix": {
    "action": "add_field_to_dict",
    "target": "_build_derived_output return dict → metadata",
    "field_name": "source_block_number",
    "field_value": "current_block (already available as local variable)",
    "rationale": "Propagate the chain block number so downstream consumers can verify data freshness"
  },

  "verification": {
    "command": "curl -s https://dkfh19zkgqq18.cloudfront.net/data/metadata.json | python3 -c \"import json,sys; d=json.load(sys.stdin); print(all(s['source_block']>0 for s in d['subnets'].values()))\"",
    "expected_result": "True",
    "test_to_add": "Assert _build_derived_output() result contains metadata.source_block_number > 0"
  },

  "classification": {
    "auto_fixable": true,
    "fix_type": "add_field_propagation",
    "risk": "low",
    "reason_safe": "Adding a field to a JSON output is additive — no existing consumer will break. The variable (current_block) already exists in scope."
  }
}
```

---

### Finding 3: Empty Badges on index.html

```json
{
  "finding_id": "CF-2026-05-19-003",
  "detected_at": "2026-05-19T06:00:00Z",
  "audit_dimension": "code_vs_output",
  "severity": "bug",
  "confidence": "certain",

  "title": "index.html renders 129 empty badge spans — template expects fields that rankings data doesn't provide",

  "observation": {
    "what_was_checked": "HTML structural integrity — empty <span> elements with badge styling",
    "expected": "Badge spans either contain text or are not rendered",
    "actual": "129 instances of empty category badge, 129 empty mining_style badge, 129 empty taoflow badge",
    "evidence_command": "curl -s https://dkfh19zkgqq18.cloudfront.net/index.html | grep -c 'text-blue-300\"></span>'",
    "evidence_result": "129"
  },

  "diagnosis": {
    "root_cause": "Producer/consumer shape mismatch. Template index.html expects {name, category, mining_style, taoflow_status}. _generate_rankings() only produces {netuid, net_tao_yield, days_to_recoup, thirty_day_projection, competitive_density, emission_trend, alpha_price, attractiveness_score}. Jinja2 silently renders empty string for missing keys.",
    "introduced_by": "bec567e created template expecting SubnetSummary shape (from design doc). 4af0b9b wired rankings data directly to generate_index() without enrichment.",
    "why_tests_missed_it": "test_site_generator.py uses _make_subnet_summary() which provides ALL fields including name/category/mining_style. Production code never produces these fields in rankings.",
    "shape_comparison": {
      "template_expects": ["netuid", "name", "category", "mining_style", "taoflow_status", "net_tao_yield", "days_to_recoup"],
      "producer_provides": ["netuid", "net_tao_yield", "days_to_recoup", "thirty_day_projection", "competitive_density", "emission_trend", "alpha_price", "attractiveness_score"],
      "missing": ["name", "category", "mining_style", "taoflow_status"],
      "extra_unused_by_template": ["thirty_day_projection", "competitive_density", "emission_trend", "alpha_price", "attractiveness_score"]
    }
  },

  "location": {
    "file_to_fix": ["lambda/templates/index.html", "lambda/src/finalizer/handler.py"],
    "line_hint": "gen.generate_index(rankings, last_updated=now)",
    "related_files": ["tests/unit/test_site_generator.py"]
  },

  "suggested_fix": {
    "action": "two_part_fix",
    "part_1": {
      "description": "Make template conditional — don't render badges when values are empty/missing",
      "file": "lambda/templates/index.html",
      "change": "Wrap each badge span in {% if subnet.field %} conditional"
    },
    "part_2": {
      "description": "Enrich rankings with available profile data before passing to template",
      "file": "lambda/src/finalizer/handler.py",
      "change": "Add _enrich_rankings_for_site() that reads PROFILE#basic from DynamoDB and taoflow_status from derived metrics"
    },
    "rationale": "Part 1 prevents empty rendering regardless of data availability. Part 2 provides data when it exists (taoflow_status is available now; name/category/mining_style will come from Stage 2 Subnet Researcher)."
  },

  "verification": {
    "command": "curl -s https://dkfh19zkgqq18.cloudfront.net/index.html | grep -c 'text-blue-300\"></span>'",
    "expected_result": "0",
    "test_to_add": "Pass real _generate_rankings() output to generate_index() and assert no empty badge spans"
  },

  "classification": {
    "auto_fixable": "partial",
    "fix_type": "template_conditional + data_enrichment",
    "risk": "medium",
    "reason_partial": "Part 1 (template conditional) is safe and auto-fixable. Part 2 (DynamoDB read + enrichment function) adds new logic and a new DynamoDB scan — should be human-reviewed.",
    "human_decision_needed": "Should we add the DynamoDB scan, or just make the template graceful with missing data?"
  }
}
```

---

## Evaluation: Could an Agent Fix Each From the Finding Alone?

### Finding 1 (nav link): ✅ YES — fully auto-fixable
- Location is exact (file + string to find)
- Fix is a string replacement (old → new)
- Verification is a curl command with expected result
- Risk is low (template change, no logic)
- An agent could: read finding → open file → replace string → run test → commit

### Finding 2 (source_block): ✅ YES — fully auto-fixable
- Location is exact (file + function)
- Fix is "add field to dict" with the value source identified
- The variable already exists in scope (current_block)
- Verification is a curl command
- An agent could: read finding → open file → add field → run test → commit

### Finding 3 (empty badges): ⚠️ PARTIAL — needs human decision
- Part 1 (template conditional) is auto-fixable
- Part 2 (enrichment function) requires a design decision: add DynamoDB scan or not?
- The finding correctly identifies this as "human_decision_needed"
- An agent could: fix Part 1 automatically, then surface Part 2 for human triage

### What's missing from the findings?

1. **Nothing critical for the simple cases** — Findings 1 and 2 have everything needed.
2. **For complex cases (Finding 3)**: The finding correctly escalates to human. But it could include **options** — "Option A: just fix template. Option B: add enrichment. Trade-offs: ..."
3. **Test code to add** — The findings say "test_to_add" in prose but don't include the actual test code. Should they? (Probably not — the agent can write the test from the description.)
4. **Dependency information** — Finding 3 mentions "Stage 2 Subnet Researcher will provide name/category." This context helps the human decide. Good to include.

---

## Derived Schema

Based on the three examples, here's what emerged as required vs optional:

### Required Fields (every finding must have these)

| Field | Type | Why |
|-------|------|-----|
| `finding_id` | string | Deduplication, reference |
| `detected_at` | ISO timestamp | When the auditor found it |
| `audit_dimension` | enum | Which audit type found it |
| `severity` | enum: bug/warning/info | Triage priority |
| `confidence` | enum: certain/likely/possible | How sure the auditor is |
| `title` | string | Human-readable one-liner |
| `observation.what_was_checked` | string | What the auditor did |
| `observation.expected` | string | What should be true |
| `observation.actual` | string | What is actually true |
| `observation.evidence_command` | string | Reproducible check |
| `observation.evidence_result` | string | What the command returned |
| `diagnosis.root_cause` | string | Why it's wrong |
| `location.file_to_fix` | string or list | Where to look |
| `suggested_fix.action` | string | What type of fix |
| `suggested_fix.rationale` | string | Why this fix |
| `verification.command` | string | How to confirm fix worked |
| `verification.expected_result` | string | What success looks like |
| `classification.auto_fixable` | bool or "partial" | Can agent fix alone? |
| `classification.risk` | enum: low/medium/high | Blast radius |

### Optional Fields (add when available, enriches context)

| Field | Type | When to include |
|-------|------|-----------------|
| `diagnosis.introduced_by` | commit hash(es) | When commit archaeology identifies origin |
| `diagnosis.why_tests_missed_it` | string | When test gap is identified |
| `diagnosis.field_trace` | object | For field_lineage dimension |
| `diagnosis.shape_comparison` | object | For shape mismatch bugs |
| `location.line_hint` | string | When specific line is known |
| `location.function` | string | When function-level is known |
| `location.related_files` | list | Other files involved |
| `suggested_fix.old_value` / `new_value` | string | For string replacements |
| `suggested_fix.part_N` | object | For multi-part fixes |
| `verification.test_to_add` | string | Description of preventive test |
| `classification.reason_safe` | string | Why auto-fix is safe |
| `classification.human_decision_needed` | string | What the human must decide |

### Enums

```
audit_dimension: spec_vs_code | code_vs_output | test_vs_production |
                 field_lineage | link_integrity | freshness |
                 commit_archaeology | live_data_edge_case

severity: bug | warning | info

confidence: certain | likely | possible

risk: low | medium | high

fix_type: string_replacement | add_field_propagation |
          template_conditional | data_enrichment |
          add_test | update_docs | requires_design
```

---

## Key Design Decisions Made

1. **Evidence is reproducible** — every finding includes a command anyone (human or agent) can run to verify the issue still exists.

2. **Diagnosis explains "why tests missed it"** — this is unique to our system. It doesn't just find the bug, it explains the systemic gap that allowed it.

3. **Classification gates auto-fix** — `auto_fixable: true` + `risk: low` = agent can fix. Anything else = human triage.

4. **Findings are self-contained** — an agent reading one finding has everything needed to understand, locate, fix, and verify. No need to read other docs or ask questions.

5. **Multi-part fixes are explicit** — Finding 3 shows that complex bugs may have a "safe part" (auto-fix) and a "decision part" (human). The schema supports this.
