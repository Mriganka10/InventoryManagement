# AWS Architecture

## Cost-optimized pilot

```text
Public user
    │ HTTPS / EB hostname
    ▼
Elastic Beanstalk single-instance environment
    └── EC2 t3.small + nginx + Docker/FastAPI
          ├── SES v2: verification links and OTP email
          ├── CloudWatch: application/health logs
          ├── S3: future invoices, imports and backups
          ├── Bedrock: optional dashboard narrative only
          └── PostgreSQL
                ├── pilot: existing/shared RDS logical database when permitted
                └── production: encrypted RDS db.t4g.micro/small
```

The pilot keeps one application process and uses server-side HTML/JavaScript, which avoids a separate frontend hosting bill. Elastic Beanstalk manages nginx, health checks, application versions and rolling replacement. Static assets are packaged with the container.

## Tenant and security boundaries

- One `workshop` is one client/tenant; every business table contains `workshop_id`.
- A normalized email maps through `workshop_users` to exactly the authorized tenant.
- Branch IDs are always validated inside the tenant.
- Signed HTTP-only, SameSite cookies contain only email and issue time.
- OTPs are HMAC-hashed, one-use and expire after ten minutes.
- SES identity verification is required before first OTP login in production.
- Stock movements and audit records are append-only through application flows.
- Purchases, transfers, count approvals and AI-proposed actions remain human-approved.
- Production database is private, encrypted and not publicly accessible.

## Scale path

When traffic or uptime requirements grow, move from EB single-instance to CloudFront + ALB + ECS/Fargate, following the Job Hunting Agent reference architecture. Keep the same Docker image and PostgreSQL schema. Add SQS workers for Excel imports, reports and forecast refreshes; add ElastiCache only when measured demand justifies it.

## Offline behaviour

The PWA service worker caches the application shell and last successful GET responses. Camera barcode scanning is client-side. Writes deliberately require connectivity so two branches cannot silently create conflicting stock ledgers. A future offline-write mode should use an explicit sync queue, device identity, idempotency keys and conflict review.

## AI boundary

The decision engine calculates deterministic evidence first. It produces reorder, expiry, receivables and capacity recommendations. Amazon Bedrock is optional and only summarizes grounded KPI/action JSON. It is never allowed to mutate stock, create a purchase, change a price or contact a customer without approval.

