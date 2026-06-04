#!/bin/bash
# Deploy pipeline to AWS with pre/post validation gates.
# Usage: ./scripts/deploy.sh [--skip-validation]
set -e

SKIP_VALIDATION=false
if [ "$1" = "--skip-validation" ]; then
    SKIP_VALIDATION=true
    echo "⚠️  --skip-validation: chain validation gate SKIPPED (emergency only)"
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
cd cdk && npx cdk deploy --require-approval never 2>&1 | tail -10
cd ..
echo ""

# Post-deploy: wait for pipeline refresh then validate
echo "5/5 Waiting 5 minutes for pipeline refresh..."
sleep 300
echo "     Running post-deploy validation..."
.venv/bin/python scripts/validate_all_metrics.py
echo ""
echo "=== Deploy complete ==="
