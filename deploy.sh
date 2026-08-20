#!/usr/bin/env bash
# Publish the page. Data is written by the daily Lambda and is not touched here.
set -euo pipefail

PROFILE="${AWS_PROFILE:-iamadmin-projects-prod}"
REGION="us-east-1"
BUCKET="coastal-flood-days-data-412602263780"
cd "$(dirname "$0")"

DIST=$(cd infra && terraform output -raw distribution_id)

# The page itself: short TTL so a deploy is visible without waiting.
aws s3 cp web/index.html "s3://$BUCKET/index.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "public, max-age=300" \
  --profile "$PROFILE" --region "$REGION"

# The basemap never changes between builds -- cache it hard.
aws s3 cp web/us-states.json "s3://$BUCKET/us-states.json" \
  --content-type "application/json" \
  --cache-control "public, max-age=604800" \
  --profile "$PROFILE" --region "$REGION"

# Only the page is invalidated. results/ is rewritten daily by the Lambda and carries
# its own one-hour Cache-Control, so invalidating it here would just cost money.
aws cloudfront create-invalidation --distribution-id "$DIST" \
  --paths "/index.html" "/us-states.json" \
  --profile "$PROFILE" --region "$REGION" --query 'Invalidation.Status' --output text

echo "deployed: https://$(cd infra && terraform output -raw site_url | sed 's|https://||')"
