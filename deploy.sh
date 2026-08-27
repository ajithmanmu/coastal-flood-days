#!/usr/bin/env bash
# Publish the page and its assets. Data is written by the daily Lambda and is not
# touched here. Safe to re-run; nothing is deleted.
set -euo pipefail

REGION="us-east-1"
BUCKET="coastal-flood-days-data-412602263780"
cd "$(dirname "$0")"

# In CI the role is assumed via OIDC and there is no named profile to pass.
PROFILE_ARG=()
if [[ -z "${CI:-}" ]]; then
  PROFILE_ARG=(--profile "${AWS_PROFILE:-iamadmin-projects-prod}")
fi

DIST="${DISTRIBUTION_ID:-$(cd infra && terraform output -raw distribution_id)}"

# Libraries and fonts are immutable: the filenames pin exact versions, and a new version
# means a new file. Cache them for a year so repeat visits never refetch a megabyte of
# MapLibre. Content types are set explicitly -- S3 guesses application/octet-stream for
# .mjs and .pbf, and a module served as octet-stream is refused by the browser.
aws s3 sync web/vendor "s3://$BUCKET/vendor" \
  --cache-control "public, max-age=31536000, immutable" \
  --exclude "*.mjs" --exclude "*.pbf" \
  "${PROFILE_ARG[@]}" --region "$REGION"

aws s3 sync web/vendor "s3://$BUCKET/vendor" \
  --cache-control "public, max-age=31536000, immutable" \
  --exclude "*" --include "*.mjs" --content-type "text/javascript" \
  "${PROFILE_ARG[@]}" --region "$REGION"

aws s3 sync web/vendor "s3://$BUCKET/vendor" \
  --cache-control "public, max-age=31536000, immutable" \
  --exclude "*" --include "*.pbf" --content-type "application/x-protobuf" \
  "${PROFILE_ARG[@]}" --region "$REGION"

# The page itself: short TTL so a deploy is visible without waiting on the edge.
aws s3 cp web/index.html "s3://$BUCKET/index.html" \
  --content-type "text/html; charset=utf-8" \
  --cache-control "public, max-age=300" \
  "${PROFILE_ARG[@]}" --region "$REGION"

# Only the page and vendor are invalidated. results/ is rewritten daily by the Lambda and
# carries its own one-hour Cache-Control, and basemap/ is content-addressed by filename --
# invalidating either here would just cost money.
aws cloudfront create-invalidation --distribution-id "$DIST" \
  --paths "/index.html" "/vendor/*" \
  "${PROFILE_ARG[@]}" --region "$REGION" --query 'Invalidation.Status' --output text

echo "deployed: https://floodhours.ajithmanmadhan.com"
