from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
import os

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    create_engine,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, sessionmaker


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


class TimestampMixin:
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow, onupdate=utcnow)


class Workshop(Base, TimestampMixin):
    __tablename__ = "workshops"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(180))
    legal_name: Mapped[str] = mapped_column(String(220), default="")
    tax_id: Mapped[str] = mapped_column(String(80), default="")
    currency: Mapped[str] = mapped_column(String(3), default="INR")
    timezone: Mapped[str] = mapped_column(String(80), default="Asia/Kolkata")
    status: Mapped[str] = mapped_column(String(30), default="active")


class User(Base, TimestampMixin):
    __tablename__ = "users"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True, index=True)
    display_name: Mapped[str] = mapped_column(String(160), default="")
    last_login_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class WorkshopUser(Base, TimestampMixin):
    __tablename__ = "workshop_users"
    __table_args__ = (UniqueConstraint("workshop_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"), index=True)
    role: Mapped[str] = mapped_column(String(30), default="owner")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class PendingRegistration(Base, TimestampMixin):
    __tablename__ = "pending_registrations"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    workshop_name: Mapped[str] = mapped_column(String(180))
    verification_status: Mapped[str] = mapped_column(String(40), default="pending")
    provider_detail: Mapped[str] = mapped_column(Text, default="")


class EmailVerification(Base, TimestampMixin):
    __tablename__ = "email_verifications"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), unique=True)
    status: Mapped[str] = mapped_column(String(40), default="pending")
    provider: Mapped[str] = mapped_column(String(30), default="ses")
    verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    detail: Mapped[str] = mapped_column(Text, default="")


class OTPCode(Base):
    __tablename__ = "otp_codes"
    id: Mapped[int] = mapped_column(primary_key=True)
    email: Mapped[str] = mapped_column(String(320), index=True)
    code_hash: Mapped[str] = mapped_column(String(128))
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    consumed: Mapped[bool] = mapped_column(Boolean, default=False)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class Branch(Base, TimestampMixin):
    __tablename__ = "branches"
    __table_args__ = (UniqueConstraint("workshop_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    code: Mapped[str] = mapped_column(String(30))
    name: Mapped[str] = mapped_column(String(180))
    address: Mapped[str] = mapped_column(Text, default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class Supplier(Base, TimestampMixin):
    __tablename__ = "suppliers"
    __table_args__ = (UniqueConstraint("workshop_id", "code"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    code: Mapped[str] = mapped_column(String(40))
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(40), default="")
    tax_id: Mapped[str] = mapped_column(String(80), default="")
    address: Mapped[str] = mapped_column(Text, default="")
    lead_time_days: Mapped[int] = mapped_column(Integer, default=7)
    rating: Mapped[Decimal] = mapped_column(Numeric(4, 2), default=0)


class Customer(Base, TimestampMixin):
    __tablename__ = "customers"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(320), default="")
    phone: Mapped[str] = mapped_column(String(40), default="", index=True)
    address: Mapped[str] = mapped_column(Text, default="")
    tax_id: Mapped[str] = mapped_column(String(80), default="")
    notes: Mapped[str] = mapped_column(Text, default="")


class Vehicle(Base, TimestampMixin):
    __tablename__ = "vehicles"
    __table_args__ = (UniqueConstraint("workshop_id", "registration_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"), index=True)
    registration_number: Mapped[str] = mapped_column(String(40))
    vin: Mapped[str] = mapped_column(String(64), default="")
    make: Mapped[str] = mapped_column(String(80), default="")
    model: Mapped[str] = mapped_column(String(100), default="")
    model_year: Mapped[int | None] = mapped_column(Integer)
    fuel_type: Mapped[str] = mapped_column(String(40), default="")
    engine_number: Mapped[str] = mapped_column(String(80), default="")
    odometer_km: Mapped[int] = mapped_column(Integer, default=0)


class InventoryItem(Base, TimestampMixin):
    __tablename__ = "inventory_items"
    __table_args__ = (UniqueConstraint("workshop_id", "sku"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    sku: Mapped[str] = mapped_column(String(80))
    barcode: Mapped[str] = mapped_column(String(100), default="", index=True)
    name: Mapped[str] = mapped_column(String(220), index=True)
    category: Mapped[str] = mapped_column(String(100), default="General")
    brand: Mapped[str] = mapped_column(String(100), default="")
    unit: Mapped[str] = mapped_column(String(30), default="each")
    description: Mapped[str] = mapped_column(Text, default="")
    purchase_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    selling_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)
    min_stock: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    reorder_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    preferred_supplier_id: Mapped[int | None] = mapped_column(ForeignKey("suppliers.id"))
    track_batch: Mapped[bool] = mapped_column(Boolean, default=False)
    track_serial: Mapped[bool] = mapped_column(Boolean, default=False)
    track_expiry: Mapped[bool] = mapped_column(Boolean, default=False)
    track_warranty: Mapped[bool] = mapped_column(Boolean, default=False)
    active: Mapped[bool] = mapped_column(Boolean, default=True)


class ItemCompatibility(Base, TimestampMixin):
    __tablename__ = "item_compatibility"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    make: Mapped[str] = mapped_column(String(80))
    model: Mapped[str] = mapped_column(String(100), default="")
    year_from: Mapped[int | None] = mapped_column(Integer)
    year_to: Mapped[int | None] = mapped_column(Integer)
    engine: Mapped[str] = mapped_column(String(80), default="")
    fuel_type: Mapped[str] = mapped_column(String(40), default="")


class StockBalance(Base, TimestampMixin):
    __tablename__ = "stock_balances"
    __table_args__ = (UniqueConstraint("workshop_id", "branch_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    quantity_on_hand: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    rack: Mapped[str] = mapped_column(String(60), default="")
    shelf: Mapped[str] = mapped_column(String(60), default="")
    bin_code: Mapped[str] = mapped_column(String(60), default="")


class StockBatch(Base, TimestampMixin):
    __tablename__ = "stock_batches"
    __table_args__ = (UniqueConstraint("workshop_id", "branch_id", "item_id", "batch_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    batch_number: Mapped[str] = mapped_column(String(100))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    manufactured_on: Mapped[date | None] = mapped_column(Date)
    expires_on: Mapped[date | None] = mapped_column(Date, index=True)
    warranty_until: Mapped[date | None] = mapped_column(Date)


class SerialNumber(Base, TimestampMixin):
    __tablename__ = "serial_numbers"
    __table_args__ = (UniqueConstraint("workshop_id", "serial_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"))
    serial_number: Mapped[str] = mapped_column(String(140))
    status: Mapped[str] = mapped_column(String(30), default="in_stock")
    warranty_until: Mapped[date | None] = mapped_column(Date)


class StockMovement(Base):
    __tablename__ = "stock_movements"
    __table_args__ = (Index("ix_stock_movement_tenant_date", "workshop_id", "occurred_at"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"), index=True)
    batch_id: Mapped[int | None] = mapped_column(ForeignKey("stock_batches.id"))
    movement_type: Mapped[str] = mapped_column(String(40))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    reference_type: Mapped[str] = mapped_column(String(40), default="manual")
    reference_id: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str] = mapped_column(Text, default="")
    performed_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class PurchaseOrder(Base, TimestampMixin):
    __tablename__ = "purchase_orders"
    __table_args__ = (UniqueConstraint("workshop_id", "po_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    supplier_id: Mapped[int] = mapped_column(ForeignKey("suppliers.id"), index=True)
    po_number: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    ordered_on: Mapped[date | None] = mapped_column(Date)
    expected_on: Mapped[date | None] = mapped_column(Date)
    received_on: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    notes: Mapped[str] = mapped_column(Text, default="")


class PurchaseOrderLine(Base):
    __tablename__ = "purchase_order_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    purchase_order_id: Mapped[int] = mapped_column(ForeignKey("purchase_orders.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"))
    quantity_ordered: Mapped[Decimal] = mapped_column(Numeric(14, 3))
    quantity_received: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    unit_cost: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)


class ServicePackage(Base, TimestampMixin):
    __tablename__ = "service_packages"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    name: Mapped[str] = mapped_column(String(180))
    description: Mapped[str] = mapped_column(Text, default="")
    labour_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)


class ServicePackageItem(Base):
    __tablename__ = "service_package_items"
    __table_args__ = (UniqueConstraint("service_package_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    service_package_id: Mapped[int] = mapped_column(ForeignKey("service_packages.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=1)


class Appointment(Base, TimestampMixin):
    __tablename__ = "appointments"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    service_package_id: Mapped[int | None] = mapped_column(ForeignKey("service_packages.id"))
    scheduled_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    status: Mapped[str] = mapped_column(String(30), default="scheduled")
    complaint: Mapped[str] = mapped_column(Text, default="")


class JobCard(Base, TimestampMixin):
    __tablename__ = "job_cards"
    __table_args__ = (UniqueConstraint("workshop_id", "job_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    appointment_id: Mapped[int | None] = mapped_column(ForeignKey("appointments.id"))
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    job_number: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="open")
    complaint: Mapped[str] = mapped_column(Text, default="")
    diagnosis: Mapped[str] = mapped_column(Text, default="")
    work_performed: Mapped[str] = mapped_column(Text, default="")
    technician: Mapped[str] = mapped_column(String(160), default="")
    odometer_km: Mapped[int] = mapped_column(Integer, default=0)
    promised_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    completed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    labour_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)


class JobCardItem(Base, TimestampMixin):
    __tablename__ = "job_card_items"
    __table_args__ = (UniqueConstraint("job_card_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    job_card_id: Mapped[int] = mapped_column(ForeignKey("job_cards.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"))
    quantity_reserved: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    quantity_issued: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    quantity_returned: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)


class Invoice(Base, TimestampMixin):
    __tablename__ = "invoices"
    __table_args__ = (UniqueConstraint("workshop_id", "invoice_number"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"), index=True)
    customer_id: Mapped[int] = mapped_column(ForeignKey("customers.id"))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    job_card_id: Mapped[int | None] = mapped_column(ForeignKey("job_cards.id"))
    invoice_number: Mapped[str] = mapped_column(String(60))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    issued_on: Mapped[date] = mapped_column(Date, default=date.today)
    due_on: Mapped[date | None] = mapped_column(Date)
    subtotal: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    discount_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    amount_paid: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    balance_due: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)


class InvoiceLine(Base):
    __tablename__ = "invoice_lines"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    line_type: Mapped[str] = mapped_column(String(30), default="part")
    item_id: Mapped[int | None] = mapped_column(ForeignKey("inventory_items.id"))
    description: Mapped[str] = mapped_column(String(240))
    quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=1)
    unit_price: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)
    tax_rate: Mapped[Decimal] = mapped_column(Numeric(6, 3), default=0)
    line_total: Mapped[Decimal] = mapped_column(Numeric(14, 2), default=0)


class Payment(Base, TimestampMixin):
    __tablename__ = "payments"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    invoice_id: Mapped[int] = mapped_column(ForeignKey("invoices.id"), index=True)
    amount: Mapped[Decimal] = mapped_column(Numeric(14, 2))
    method: Mapped[str] = mapped_column(String(40), default="cash")
    reference: Mapped[str] = mapped_column(String(120), default="")
    paid_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


class StockCount(Base, TimestampMixin):
    __tablename__ = "stock_counts"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    branch_id: Mapped[int] = mapped_column(ForeignKey("branches.id"))
    status: Mapped[str] = mapped_column(String(30), default="draft")
    method: Mapped[str] = mapped_column(String(40), default="blind_count")
    counted_by: Mapped[int] = mapped_column(ForeignKey("users.id"))
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    approved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class StockCountLine(Base):
    __tablename__ = "stock_count_lines"
    __table_args__ = (UniqueConstraint("stock_count_id", "item_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    stock_count_id: Mapped[int] = mapped_column(ForeignKey("stock_counts.id"), index=True)
    item_id: Mapped[int] = mapped_column(ForeignKey("inventory_items.id"))
    system_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    counted_quantity: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    variance: Mapped[Decimal] = mapped_column(Numeric(14, 3), default=0)
    reason: Mapped[str] = mapped_column(Text, default="")


class AuditLog(Base):
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    workshop_id: Mapped[int] = mapped_column(ForeignKey("workshops.id"), index=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(80))
    entity_type: Mapped[str] = mapped_column(String(80))
    entity_id: Mapped[int | None] = mapped_column(Integer)
    before_data: Mapped[dict] = mapped_column(JSON, default=dict)
    after_data: Mapped[dict] = mapped_column(JSON, default=dict)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)


def _database_url() -> str:
    value = os.getenv("INVENTORY_DATABASE_URL", "sqlite:///data/inventory.db")
    if value.startswith("postgres://"):
        value = "postgresql+psycopg://" + value.removeprefix("postgres://")
    elif value.startswith("postgresql://") and "+psycopg" not in value:
        value = "postgresql+psycopg://" + value.removeprefix("postgresql://")
    if value.startswith("sqlite:///"):
        Path(value.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
    return value


DATABASE_URL = _database_url()
engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    connect_args={"check_same_thread": False} if DATABASE_URL.startswith("sqlite") else {},
)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False)


def init_db() -> None:
    Base.metadata.create_all(engine)
