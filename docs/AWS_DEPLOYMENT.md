# Elastic Beanstalk Deployment Runbook

Region: `ap-south-1`

## Pilot resources

- Elastic Beanstalk application: `workshop-inventory`
- Environment: `workshop-inventory-pilot`
- Platform: Docker running on 64-bit Amazon Linux 2023
- Mode: single instance
- Health endpoint: `/health`
- Database: PostgreSQL recommended; SQLite allowed only for disposable pilot data
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

Run `scripts/aws/deploy_elastic_beanstalk.sh` after configuring AWS CLI credentials and the required environment variables. The script performs identity preflight, packages an immutable source bundle, creates or updates the environment and waits for health.

## Production hardening

- Replace the default EB hostname with ACM + Route 53 HTTPS.
- Put RDS in private subnets; enable encryption, backups and deletion protection.
- Store database and signing secrets in Secrets Manager/SSM instead of plain EB environment properties.
- Move SES out of sandbox and verify a domain with DKIM.
- Set CloudWatch retention and alarms for 5xx rate, instance health and database storage.
- Run tenant-isolation, backup-restore and invoice tax acceptance tests before real customers.
