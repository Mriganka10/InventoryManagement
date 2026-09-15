# AWS Architecture

## Cost-optimized production

```text
Public user
    │ HTTPS / CloudFront hostname
    ▼
WorkshopOS CloudFront distribution (usage-priced; default hostname initially)
    │ X-Kairoz-Application: inventory
    ▼
Existing shared Application Load Balancer
    ▼
Isolated WorkshopOS ECS service on the existing shared Graviton capacity
    └── Docker/FastAPI web task
          ├── SES v2: verification links and OTP email
          ├── Dedicated CloudWatch log group
          ├── Dedicated S3 bucket/prefix
          ├── Bedrock: optional dashboard narrative only
          └── Dedicated database and role on existing shared encrypted PostgreSQL
```

The application keeps one web process and uses server-side HTML/JavaScript, avoiding a separate frontend host. ECS manages health checks and rolling replacement. The deployment performs a capacity preflight and refuses to scale the shared EC2 group unless explicitly authorized, preventing surprise compute cost.

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

When measured traffic or uptime requirements outgrow the shared Graviton host, add capacity behind the existing ECS capacity provider or move this task to Fargate without changing the Docker image or PostgreSQL schema. Add SQS workers for Excel imports, reports and forecast refreshes; add ElastiCache only when measured demand justifies it.

## Offline behaviour

The PWA service worker caches the application shell and last successful GET responses. Camera barcode scanning is client-side. Writes deliberately require connectivity so two branches cannot silently create conflicting stock ledgers. A future offline-write mode should use an explicit sync queue, device identity, idempotency keys and conflict review.

## AI boundary

The decision engine calculates deterministic evidence first. It produces reorder, expiry, receivables and capacity recommendations. Amazon Bedrock is optional and only summarizes grounded KPI/action JSON. It is never allowed to mutate stock, create a purchase, change a price or contact a customer without approval.
