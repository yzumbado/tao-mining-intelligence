#!/bin/bash
# TAO Pipeline — Morning Check (2026-05-19)
# Run: bash scripts/morning_check.sh

echo "=== Staking Rankings (where to stake your TAO) ==="
aws s3 cp --profile tao s3://tao-intelligence-site-651484323929/data/staking_rankings.json - 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'Subnets ranked: {len(d)}')
print()
print(f'{\"SN\":>4} {\"APY%\":>8} {\"Daily/10TAO\":>12} {\"Validators\":>10} {\"Alpha Price\":>11} {\"Break-even\":>10}')
print('-' * 60)
for s in d[:15]:
    print(f'{s[\"netuid\"]:>4} {s[\"net_apy_percent\"]:>8.2f} {s[\"daily_tao_per_10_staked\"]:>12.6f} {s[\"active_validators\"]:>10} {s[\"alpha_price\"]:>11.6f} {s[\"break_even_alpha_depreciation\"]:>10.4f}')
"

echo ""
echo "=== Mining Rankings (should be differentiated now) ==="
aws s3 cp --profile tao s3://tao-intelligence-site-651484323929/data/rankings.json - 2>/dev/null | python3 -c "
import json, sys
d = json.load(sys.stdin)
print(f'{\"SN\":>4} {\"Yield\":>8} {\"Score\":>8}')
for s in d[:10]:
    print(f'{s[\"netuid\"]:>4} {s[\"net_tao_yield\"]:>8.2f} {s[\"attractiveness_score\"]:>8.4f}')
scores = set(f'{s[\"attractiveness_score\"]:.4f}' for s in d[:10])
print(f'\nDifferentiated: {\"YES ✅\" if len(scores) > 1 else \"NO ⚠️ (wait for re-collection)\"}')
"

echo ""
echo "=== HTML Site ==="
curl -s -o /dev/null -w "index.html: HTTP %{http_code}\n" https://dkfh19zkgqq18.cloudfront.net/index.html

echo ""
echo "=== Pipeline Health ==="
echo "DLQ: $(aws sqs get-queue-attributes --profile tao --region us-east-1 --queue-url 'https://sqs.us-east-1.amazonaws.com/651484323929/tao-process-subnet-dlq' --attribute-names ApproximateNumberOfMessages --query 'Attributes.ApproximateNumberOfMessages' --output text)"
echo "Schedules: $(aws scheduler list-schedules --profile tao --region us-east-1 --query 'Schedules | length(@)' --output text)"
