#!/usr/bin/env bash
set -euo pipefail

AWS_REGION="${AWS_REGION:-ap-south-1}"
EB_APPLICATION_NAME="${EB_APPLICATION_NAME:-workshop-inventory}"
EB_ENVIRONMENT_NAME="${EB_ENVIRONMENT_NAME:-workshop-inventory-pilot}"
EB_INSTANCE_TYPE="${EB_INSTANCE_TYPE:-t3.small}"

: "${INVENTORY_SECRET_KEY:?Set INVENTORY_SECRET_KEY}"
: "${INVENTORY_DATABASE_URL:?Set INVENTORY_DATABASE_URL}"

aws sts get-caller-identity >/dev/null
command -v eb >/dev/null || { echo "Install awsebcli before deployment."; exit 1; }

if [[ ! -d .elasticbeanstalk ]]; then
  eb init "$EB_APPLICATION_NAME" --platform docker --region "$AWS_REGION"
fi
if ! eb status "$EB_ENVIRONMENT_NAME" >/dev/null 2>&1; then
  eb create "$EB_ENVIRONMENT_NAME" --single --instance-type "$EB_INSTANCE_TYPE"
fi
eb setenv \
  AWS_REGION="$AWS_REGION" \
  INVENTORY_SECRET_KEY="$INVENTORY_SECRET_KEY" \
  INVENTORY_DATABASE_URL="$INVENTORY_DATABASE_URL" \
  INVENTORY_COOKIE_SECURE=true \
  INVENTORY_DEV_RETURN_OTP=false \
  INVENTORY_EMAIL_PROVIDER=ses \
  INVENTORY_SES_REGION="$AWS_REGION"
eb deploy "$EB_ENVIRONMENT_NAME"
eb health "$EB_ENVIRONMENT_NAME" --refresh
eb status "$EB_ENVIRONMENT_NAME"
