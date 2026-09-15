# Shared ECS Deployment Runbook

Region: `ap-south-1`

## WorkshopOS resources

- Existing stack: `kairoz-production-platform`
- ECS service: `kairoz-inventory-web`
- Container repository: `kairoz/inventory`
- ALB target group: `kairoz-inventory`
- Routing header: `X-Kairoz-Application: inventory`
- Database/role: `inventory` / `inventory_app` on shared PostgreSQL
- Runtime secret: `/kairoz/production/inventory/environment`
- Database credential secret: `/kairoz/production/inventory/database`
- CloudWatch logs: `/kairoz/production/inventory`
- CloudFront distribution: `E2EWEQPY3RID5K`
- Public entrypoint: `https://djn5rprshgdy5.cloudfront.net`
- Health endpoint: `/health`
- Email: Amazon SES v2

## Required environment values

```text
INVENTORY_SECRET_KEY=<long random secret>
INVENTORY_DATABASE_URL=<postgresql URL>
INVENTORY_COOKIE_SECURE=true
INVENTORY_DEV_RETURN_OTP=false
INVENTORY_EMAIL_PROVIDER=ses
INVENTORY_SES_REGION=ap-south-1
INVENTORY_SES_FROM=<preferred verified sender; optional for self-sender pilot>
AWS_REGION=ap-south-1
```

Grant the EC2 instance profile `ses:GetEmailIdentity`, `ses:CreateEmailIdentity` and `ses:SendEmail`. Add `bedrock:InvokeModel` only when `INVENTORY_BEDROCK_MODEL_ID` is configured.

## Deployment

Run `python scripts/aws/deploy_shared_ecs.py` from an authenticated AWS shell. It discovers the existing shared platform, refuses an EC2 scale-out unless `ALLOW_SCALE_OUT=1`, creates only isolated usage-priced resources, builds the ARM64 image on the existing ECS host, deploys one web task, creates the CloudFront entrypoint, and waits for public health.

## Production hardening

- Replace the default CloudFront hostname with an ACM/Route 53 custom domain.
- Verify that the shared private RDS instance retains encryption, backups and deletion protection.
- Keep application and database credentials in the dedicated Secrets Manager secrets listed above.
- Move SES out of sandbox and verify a domain with DKIM.
- Set CloudWatch retention and alarms for 5xx rate, instance health and database storage.
- Run tenant-isolation, backup-restore and invoice tax acceptance tests before real customers.

## Verified deployment state

On 15 September 2026, `/health` returned `{"status":"ok","service":"workshop-os"}`, `/login` returned HTTP 200, and ECS reported an ACTIVE service with desired/running `1/1` and a completed rollout. The shared cluster remained at one EC2 container host, and all temporary database/image-build IAM policies had been removed.
