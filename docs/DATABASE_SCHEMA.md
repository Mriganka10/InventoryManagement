# Database Design

The operational schema is normalized and tenant-scoped. SQLAlchemy models in `src/inventory_management/models.py` are executable schema definitions for SQLite and PostgreSQL.

## Identity and tenancy

| Table | Purpose |
|---|---|
| `workshops` | One customer/client tenant, currency and timezone. |
| `users` | Normalized email identities. |
| `workshop_users` | Tenant membership, role and active state. |
| `branches` | Multiple operating locations belonging to one workshop. |
| `pending_registrations` | Workshop name captured before verification and first login. |
| `email_verifications` | SES/provider verification state and timestamps. |
| `otp_codes` | Hashed, expiring, single-use sign-in codes. |

## Parties and vehicles

| Table | Purpose |
|---|---|
| `suppliers` | Supplier contact, tax and lead-time performance inputs. |
| `customers` | Workshop customer master. |
| `vehicles` | Customer-owned vehicles, VIN, registration, make/model and odometer. |

## Inventory and control

| Table | Purpose |
|---|---|
| `inventory_items` | SKU, barcode, category, brand, unit, pricing, tax and tracking policy. |
| `item_compatibility` | Trusted vehicle make/model/year/engine fitment records. |
| `stock_balances` | Materialized on-hand/reserved balance for each branch and item. |
| `stock_batches` | Batch quantity, manufacture, expiry and warranty dates. |
| `serial_numbers` | Individual serialized units and lifecycle status. |
| `stock_movements` | Immutable receipt/issue/return/damage/expiry/transfer/adjustment ledger. |
| `stock_counts` | Blind physical-count header and maker-checker approval. |
| `stock_count_lines` | System quantity, counted quantity, variance and reason. |

## Purchasing, service and billing

| Table | Purpose |
|---|---|
| `purchase_orders` / `purchase_order_lines` | Supplier orders, expected/actual receipt and landed values. |
| `service_packages` / `service_package_items` | Standard service recipes used for automatic reservation. |
| `appointments` | Scheduled service per branch/customer/vehicle. |
| `job_cards` / `job_card_items` | Diagnosis, technician, parts reserved/issued/returned and labour. |
| `invoices` / `invoice_lines` | Parts/labour/service billing, tax, discounts and balance. |
| `payments` | Cash/card/UPI/bank receipts and references. |
| `audit_log` | Actor, action, entity, before/after state and timestamp. |

## Important invariants

1. Unique SKU and vehicle registration are enforced per workshop, not globally.
2. Stock balance is unique by workshop + branch + item.
3. Every balance change has a corresponding stock movement.
4. On-hand and reserved stock cannot become negative through supported APIs.
5. Serialized quantities require one unique serial per unit.
6. Issuing a reserved part releases the reservation before reducing on-hand stock.
7. Invoice payments cannot exceed the outstanding balance.
8. Physical-count variances require owner or manager approval.
9. Foreign IDs are looked up with the authenticated workshop ID before use.

## Opening-stock verification

Use a two-pass maker-checker migration: dry-run validation, audited import, blind physical barcode count by a second person, manager variance approval, then retention of the signed count and source workbook. This provides much stronger assurance than spreadsheet totals alone.

