#!/bin/bash
# Deploy pipeline to AWS with pre/post validation gates.
# Usage: ./scripts/deploy.sh
set -e

echo "=== TAO Pipeline Deploy ==="
echo ""

# Pre-deploy: run tests
echo "1/4 Running tests..."
.venv/bin/pytest tests/ -q --tb=line 2>&1 | tail -3
echo ""

# Pre-deploy: validate metrics against live chain
echo "2/4 Running cross-provider validation (pre-deploy)..."
echo "     (Failures expected if code has formula changes not yet deployed)"
.venv/bin/python scripts/validate_all_metrics.py || true
echo ""

# Deploy
echo "3/4 Deploying CDK stack..."
cd cdk && npx cdk deploy --require-approval never 2>&1 | tail -10
cd ..
echo ""

# Post-deploy: wait for pipeline refresh then validate
echo "4/4 Waiting 5 minutes for pipeline refresh..."
sleep 300
echo "     Running post-deploy validation..."
.venv/bin/python scripts/validate_all_metrics.py
echo ""
echo "=== Deploy complete ==="
