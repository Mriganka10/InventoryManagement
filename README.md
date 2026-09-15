# WorkshopOS Inventory Management

WorkshopOS is a multi-tenant automobile workshop operating system. Each workshop is an isolated client workspace and can operate multiple branches from one verified owner login.

## Included capabilities

- Passwordless email authentication with new-user verification and expiring OTPs.
- Workshop and branch isolation with owner/manager/stores/technician/accountant roles.
- Complete item master: SKU, barcode, category, brand, unit, price, tax, reorder settings, location, compatibility and tracking flags.
- Branch-level stock ledger, reservations and availability with no direct quantity overwrite.
- Batch, serial-number, warranty and expiry tracking.
- Suppliers, purchase orders and stock receipt.
- Customers, vehicles, appointments, job cards and parts issue.
- Service-package recipes with automatic parts reservation and shortage reporting.
- Invoices, payments and receivables.
- Excel template, dry-run validation and controlled opening-stock import.
- Blind physical-count and manager approval workflow.
- Browser barcode scanning and printable Code 128 PDF labels.
- KPI dashboards, sales/category charts, reorder table and expiry watch.
- Explainable decision recommendations, with optional Amazon Bedrock executive summaries.
- Installable PWA shell with cached read experience during connectivity loss.

## Local run

```bash
python -m venv .venv
.venv/bin/pip install -e '.[dev]'
INVENTORY_SECRET_KEY=local-secret INVENTORY_DEV_RETURN_OTP=true INVENTORY_COOKIE_SECURE=false .venv/bin/python -m inventory_management
```

Open `http://localhost:8000/register`. Local development returns the OTP in the interface. Production never exposes OTPs.

## Configuration

Copy `.env.example` values into your runtime environment. Production minimums are:

- `INVENTORY_DATABASE_URL`: PostgreSQL connection string.
- `INVENTORY_SECRET_KEY`: long random cookie/OTP signing secret.
- `INVENTORY_EMAIL_PROVIDER=ses`.
- `INVENTORY_SES_FROM`: required verified sender/domain used for verification links and OTPs.
- `INVENTORY_PUBLIC_BASE_URL`: public HTTPS origin used in signed email-verification links.
- `INVENTORY_DEV_RETURN_OTP=false`.
- `INVENTORY_COOKIE_SECURE=true`.

AWS SES sandbox accounts can send only to verified recipients. Move SES to production before onboarding arbitrary workshop owners.

## API

Interactive API documentation is available at `/docs`. All business endpoints require the signed HTTP-only session cookie. Every business query is scoped by the authenticated user's `workshop_id`.

## Deployment

See [AWS architecture](docs/ARCHITECTURE.md), [database design](docs/DATABASE_SCHEMA.md), and [deployment runbook](docs/AWS_DEPLOYMENT.md).

Production reuses the existing Kairoz CloudFront, ALB, ECS/EC2, RDS and networking platform. WorkshopOS adds no standalone Elastic Beanstalk instance or RDS instance. SQLite is local-test only.

Live production endpoint: [https://djn5rprshgdy5.cloudfront.net](https://djn5rprshgdy5.cloudfront.net)
