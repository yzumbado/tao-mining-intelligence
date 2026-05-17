# Fix Plan: Import Path & Packaging Problem

## Problem Statement

The pipeline has a deployment-blocking bug: **the Docker container cannot resolve imports at runtime**.

- Source code uses `from src.config import ...` (28 occurrences across 9 files)
- CDK uses `cmd=["src.orchestrator.handler.handle"]` (expects `src` package prefix)
- Dockerfile does `COPY src/ ${LAMBDA_TASK_ROOT}/` (flattens — no `src/` prefix in container)

**Result**: Lambda will fail with `ModuleNotFoundError: No module named 'src'` on every invocation.

**Why tests pass**: Tests add both `lambda/` AND `lambda/src/` to sys.path, so Python resolves `from src.X` via the `lambda/` path. The container only has one path (`/var/task/`).

---

## Fix Options

### Option A: Fix Dockerfile (RECOMMENDED — minimal change)

**Change**: `COPY src/ ${LAMBDA_TASK_ROOT}/` → `COPY src/ ${LAMBDA_TASK_ROOT}/src/`

**Impact**: 1 line changed. All imports and CDK CMD values stay the same.

**Container layout after fix**:
```
/var/task/
├── src/
│   ├── __init__.py
│   ├── config.py
│   ├── orchestrator/handler.py
│   ├── processor/handler.py
│   └── ...
└── templates/
```

**Verification**:
```bash
docker build -t test-imports lambda/ && \
docker run --rm test-imports python -c "from src.processor.handler import handle; print('OK')"
```

### Option B: Remove `src.` prefix from all imports

**Change**: Rewrite all 28 `from src.X` imports to `from X`, fix CDK CMD values, fix `__init__.py` re-exports.

**Impact**: 9+ files modified, CDK stack modified, all tests need updating. High risk of introducing new bugs.

**Not recommended** — too many moving parts for the same outcome.

---

## Execution Plan (Option A)

### Step 1: Fix Dockerfile
```dockerfile
# Before:
COPY src/ ${LAMBDA_TASK_ROOT}/

# After:
COPY src/ ${LAMBDA_TASK_ROOT}/src/
```

### Step 2: Fix templates COPY (templates must stay at /var/task/templates/)
```dockerfile
# This stays the same — templates are referenced by relative path
COPY templates/ ${LAMBDA_TASK_ROOT}/templates/
```

### Step 3: Verify Docker build + import resolution
```bash
docker build -t test-imports lambda/
docker run --rm test-imports python -c "from src.orchestrator.handler import handle; print('orchestrator OK')"
docker run --rm test-imports python -c "from src.subnet_collector.handler import handle; print('collector OK')"
docker run --rm test-imports python -c "from src.processor.handler import handle; print('processor OK')"
docker run --rm test-imports python -c "from src.finalizer.handler import handle; print('finalizer OK')"
```

### Step 4: Verify all tests still pass
```bash
pytest tests/ -v
```

### Step 5: Add a packaging smoke test (prevents regression)
Add to `tests/cdk/test_pipeline_stack.py` or a new `tests/test_packaging.py`:
```python
def test_dockerfile_preserves_src_prefix():
    """Verify Dockerfile COPY preserves the src/ package prefix."""
    dockerfile = Path("lambda/Dockerfile").read_text()
    assert "COPY src/ ${LAMBDA_TASK_ROOT}/src/" in dockerfile, (
        "Dockerfile must COPY src/ into src/ subdirectory to preserve import paths"
    )
```

### Step 6: Centralize test path setup (prevents future drift)
Create `tests/conftest.py`:
```python
import sys
import os

# Single source of truth for test import paths.
# Mirrors the container layout: lambda/ is the root, src/ is a package within it.
_lambda_dir = os.path.join(os.path.dirname(__file__), "..", "lambda")
if _lambda_dir not in sys.path:
    sys.path.insert(0, _lambda_dir)
```

Then remove all `sys.path.insert()` calls from individual test files (22 files).

---

## What This Prevents

| Risk | Before Fix | After Fix |
|------|-----------|-----------|
| Lambda can't find handler | ❌ BROKEN | ✅ Fixed |
| Internal imports fail in container | ❌ BROKEN | ✅ Fixed |
| Tests mask import bugs | ⚠️ Yes (dual path) | ✅ Single path via conftest |
| Future Dockerfile changes break imports | ⚠️ No guard | ✅ Packaging smoke test |
| Scripts break silently | ⚠️ No guard | ✅ Conftest covers scripts too |

---

## Priority

**MUST FIX BEFORE `cdk deploy`**. Without this fix, all 4 Lambda functions will fail on cold start with `ModuleNotFoundError`.

Estimated effort: 30 minutes (Step 1-4), 1 hour (Steps 5-6 for regression prevention).
