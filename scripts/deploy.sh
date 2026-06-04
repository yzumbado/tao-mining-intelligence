#!/bin/bash
# Deploy pipeline to AWS with pre/post validation gates.
# Usage: ./scripts/deploy.sh [--skip-validation]
set -e

SKIP_VALIDATION=false
if [ "$1" = "--skip-validation" ]; then
    SKIP_VALIDATION=true
fi

# --- Prerequisites ---
echo "=== Prerequisites ==="
FAIL=false

if ! .venv/bin/python --version 2>/dev/null | grep -q "3.12"; then
    echo "❌ Python 3.12 venv not found. Run: /opt/homebrew/bin/python3.12 -m venv .venv && pip install -e '.[dev]'"
    FAIL=true
else
    echo "✅ Python 3.12 venv"
fi

if ! docker info >/dev/null 2>&1; then
    echo "❌ Docker not running. Run: colima start"
    FAIL=true
else
    echo "✅ Docker (Colima)"
fi

if ! aws sts get-caller-identity --profile tao >/dev/null 2>&1; then
    echo "❌ AWS profile 'tao' not authenticated. Check ~/.aws/credentials"
    FAIL=true
else
    echo "✅ AWS profile 'tao'"
fi

if ! which npx >/dev/null 2>&1; then
    echo "❌ npx not found. Install Node.js"
    FAIL=true
else
    echo "✅ Node.js/npx"
fi

if [ "$FAIL" = true ]; then
    echo ""
    echo "Fix prerequisites above before deploying."
    exit 1
fi
echo ""

if [ "$SKIP_VALIDATION" = true ]; then
    echo "⚠️  --skip-validation: chain validation gate SKIPPED"
    echo ""
fi

echo "=== TAO Pipeline Deploy ==="
echo ""

# Pre-deploy: run tests
echo "1/5 Running tests..."
.venv/bin/pytest tests/ -q --tb=line 2>&1 | tail -3
echo ""

# Pre-deploy: HARD validation gate (blocks deploy on failure)
echo "2/5 Cross-provider validation gate..."
if [ "$SKIP_VALIDATION" = true ]; then
    echo "     SKIPPED (--skip-validation flag)"
else
    .venv/bin/python scripts/validate_all_metrics.py
    echo "     ✅ Validation gate PASSED"
fi
echo ""

# Pre-deploy: provider spot check (soft warning, never blocks)
echo "3/5 Provider spot check (bittensor.ai)..."
.venv/bin/python scripts/validate_against_providers.py || echo "     ⚠️  Provider spot check failed (non-blocking)"
echo ""

# Deploy
echo "4/5 Deploying CDK stack..."
npx cdk deploy --require-approval never --profile tao --app ".venv/bin/python cdk/app.py" 2>&1 | tail -10
echo ""

# Post-deploy: quick RPC spot check (no 5-min wait needed for price)
echo "5/5 Post-deploy spot check..."
sleep 30  # brief wait for at least one subnet to refresh
.venv/bin/python scripts/validate_against_providers.py
echo ""
echo "=== Deploy complete ==="
