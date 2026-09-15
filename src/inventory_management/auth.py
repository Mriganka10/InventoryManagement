from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import re
import secrets
import time
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
import smtplib

from fastapi import HTTPException
from sqlalchemy import select

from .models import (
    Branch,
    EmailVerification,
    OTPCode,
    PendingRegistration,
    SessionLocal,
    User,
    Workshop,
    WorkshopUser,
    utcnow,
)

SESSION_COOKIE = "workshop_session"
SESSION_MAX_AGE = int(os.getenv("INVENTORY_SESSION_MAX_AGE_SECONDS", str(60 * 60 * 12)))
OTP_TTL_MINUTES = int(os.getenv("INVENTORY_OTP_TTL_MINUTES", "10"))
VERIFICATION_TTL_HOURS = int(os.getenv("INVENTORY_VERIFICATION_TTL_HOURS", "24"))
SECRET = os.getenv("INVENTORY_SECRET_KEY", "local-dev-change-me")
COOKIE_SECURE = os.getenv("INVENTORY_COOKIE_SECURE", "false").lower() == "true"
DEV_RETURN_OTP = os.getenv("INVENTORY_DEV_RETURN_OTP", "true").lower() == "true"
EMAIL_PROVIDER = os.getenv("INVENTORY_EMAIL_PROVIDER", "console").strip().lower()
SES_REGION = os.getenv("INVENTORY_SES_REGION", os.getenv("AWS_REGION", "ap-south-1"))
PUBLIC_BASE_URL = os.getenv("INVENTORY_PUBLIC_BASE_URL", "http://localhost:8000").rstrip("/")
EMAIL_PATTERN = re.compile(r"^(?=.{6,254}$)(?!.*\.\.)[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}$", re.I)
logger = logging.getLogger(__name__)

if COOKIE_SECURE and SECRET == "local-dev-change-me":
    raise RuntimeError("Set INVENTORY_SECRET_KEY before enabling secure cookies.")


def normalize_email(email: str) -> str:
    return email.strip().lower()


def validate_email(email: str) -> str:
    value = normalize_email(email)
    local = value.split("@", 1)[0] if "@" in value else ""
    if not EMAIL_PATTERN.fullmatch(value) or len(local) > 64 or local.startswith(".") or local.endswith("."):
        raise HTTPException(400, "Enter a valid email address.")
    return value


def _signed(payload: dict) -> str:
    raw = base64.urlsafe_b64encode(json.dumps(payload, separators=(",", ":")).encode()).decode().rstrip("=")
    signature = hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    return f"{raw}.{signature}"


def _unsigned(token: str) -> dict:
    raw, signature = token.split(".", 1)
    expected = hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise ValueError("Invalid signature")
    return json.loads(base64.urlsafe_b64decode((raw + "=" * (-len(raw) % 4)).encode()))


def session_token(email: str) -> str:
    return _signed({"email": normalize_email(email), "iat": int(time.time())})


def session_email(token: str | None) -> str | None:
    if not token:
        return None
    try:
        payload = _unsigned(token)
        if int(payload.get("iat", 0)) + SESSION_MAX_AGE < int(time.time()):
            return None
        return validate_email(str(payload["email"]))
    except Exception:
        return None


def require_email(token: str | None) -> str:
    email = session_email(token)
    if not email:
        raise HTTPException(401, "Sign in required.")
    return email


def _otp_hash(email: str, otp: str) -> str:
    return hmac.new(SECRET.encode(), f"{normalize_email(email)}:{otp}".encode(), hashlib.sha256).hexdigest()


def verification_token(email: str) -> str:
    return _signed({"purpose": "verify-email", "email": validate_email(email), "iat": int(time.time())})


def confirm_email(token: str) -> str:
    try:
        payload = _unsigned(token)
        issued_at = int(payload.get("iat", 0))
        if payload.get("purpose") != "verify-email" or issued_at + VERIFICATION_TTL_HOURS * 3600 < int(time.time()):
            raise ValueError("Expired or incorrect token")
        email = validate_email(str(payload["email"]))
    except Exception as exc:
        raise HTTPException(400, "This verification link is invalid or expired. Request a new link.") from exc
    with SessionLocal.begin() as db:
        pending = db.scalar(select(PendingRegistration).where(PendingRegistration.email == email))
        if not pending:
            raise HTTPException(400, "No pending workshop registration exists for this email.")
        record = db.scalar(select(EmailVerification).where(EmailVerification.email == email))
        if record:
            record.status, record.provider = "SUCCESS", EMAIL_PROVIDER
            record.detail, record.verified_at = "WorkshopOS signed verification link confirmed.", utcnow()
        else:
            db.add(EmailVerification(email=email, status="SUCCESS", provider=EMAIL_PROVIDER, detail="WorkshopOS signed verification link confirmed.", verified_at=utcnow()))
        pending.verification_status = "verified"
    return email


def register_email(email: str, workshop_name: str) -> dict:
    email = validate_email(email)
    workshop_name = workshop_name.strip()
    if len(workshop_name) < 2:
        raise HTTPException(400, "Workshop name is required.")
    with SessionLocal.begin() as db:
        existing = db.scalar(select(User).where(User.email == email))
        if existing:
            return {"status": "verified", "email": email, "message": "Account exists. Request an OTP to sign in."}
        pending = db.scalar(select(PendingRegistration).where(PendingRegistration.email == email))
        if pending:
            pending.workshop_name = workshop_name
        else:
            db.add(PendingRegistration(email=email, workshop_name=workshop_name))

    status = "PENDING" if EMAIL_PROVIDER in {"ses", "smtp"} else "SUCCESS"
    if status == "PENDING" and not _send_verification_link(email, verification_token(email)):
        raise HTTPException(503, "The verification email could not be sent. Please try again shortly.")

    with SessionLocal.begin() as db:
        record = db.scalar(select(EmailVerification).where(EmailVerification.email == email))
        detail = "WorkshopOS verification link accepted for delivery." if status == "PENDING" else "Local verification completed."
        if record:
            record.status, record.provider, record.detail = status, EMAIL_PROVIDER, detail
            record.verified_at = utcnow() if status == "SUCCESS" else None
        else:
            db.add(EmailVerification(email=email, status=status, provider=EMAIL_PROVIDER, detail=detail, verified_at=utcnow() if status == "SUCCESS" else None))
    return {
        "status": "verified" if status == "SUCCESS" else "pending",
        "email": email,
        "message": "Verification link accepted for delivery. Check Inbox and Spam, then click it before requesting an OTP." if status != "SUCCESS" else "Email verified. Request an OTP to sign in.",
    }


def resend_verification(email: str) -> dict:
    email = validate_email(email)
    with SessionLocal.begin() as db:
        if db.scalar(select(User).where(User.email == email)):
            return {"status": "verified", "email": email, "message": "Account already exists. Request an OTP to sign in."}
        pending = db.scalar(select(PendingRegistration).where(PendingRegistration.email == email))
        if not pending:
            raise HTTPException(404, "No pending registration exists for this email. Create the workshop first.")
    if EMAIL_PROVIDER not in {"ses", "smtp"}:
        return {"status": "verified", "email": email, "message": "Email is verified in local development."}
    if not _send_verification_link(email, verification_token(email)):
        raise HTTPException(503, "The verification email could not be sent. Please try again shortly.")
    with SessionLocal.begin() as db:
        record = db.scalar(select(EmailVerification).where(EmailVerification.email == email))
        if record:
            record.status, record.provider = "PENDING", EMAIL_PROVIDER
            record.detail, record.verified_at = "WorkshopOS verification link re-sent and accepted for delivery.", None
        else:
            db.add(EmailVerification(email=email, status="PENDING", provider=EMAIL_PROVIDER, detail="WorkshopOS verification link re-sent and accepted for delivery."))
    return {"status": "pending", "email": email, "message": "A fresh verification link was accepted for delivery. Check Inbox and Spam."}


def request_otp(email: str) -> dict:
    email = validate_email(email)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        verification = db.scalar(select(EmailVerification).where(EmailVerification.email == email))
        if EMAIL_PROVIDER in {"ses", "smtp"} and not user:
            if not verification or verification.status.upper() != "SUCCESS" or not verification.verified_at or not verification.detail.startswith("WorkshopOS signed"):
                raise HTTPException(403, "Email is not verified. Use New workshop registration and click the WorkshopOS verification link first.")
        if not user:
            pending = db.scalar(select(PendingRegistration).where(PendingRegistration.email == email))
            if not pending:
                raise HTTPException(404, "No workshop account exists for this email. Register first.")

        db.query(OTPCode).filter(OTPCode.email == email, OTPCode.consumed.is_(False)).update({"consumed": True})
        otp = f"{secrets.randbelow(1_000_000):06d}"
        db.add(OTPCode(email=email, code_hash=_otp_hash(email, otp), expires_at=utcnow() + timedelta(minutes=OTP_TTL_MINUTES)))

    sent = _send_otp(email, otp)
    if not sent and not DEV_RETURN_OTP:
        raise HTTPException(503, "OTP email delivery is not configured or failed.")
    result = {"status": "sent", "email": email, "expires_in_minutes": OTP_TTL_MINUTES}
    if DEV_RETURN_OTP and not sent:
        result["dev_otp"] = otp
    return result


def consume_otp(email: str, otp: str) -> User:
    email = validate_email(email)
    with SessionLocal.begin() as db:
        record = db.scalar(
            select(OTPCode)
            .where(OTPCode.email == email, OTPCode.code_hash == _otp_hash(email, otp.strip()), OTPCode.consumed.is_(False))
            .order_by(OTPCode.created_at.desc())
        )
        expires = record.expires_at if record else None
        if expires and expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if not record or not expires or expires < utcnow():
            if record:
                record.attempts += 1
            raise HTTPException(400, "Invalid or expired OTP.")
        record.consumed = True
        user = db.scalar(select(User).where(User.email == email))
        if not user:
            pending = db.scalar(select(PendingRegistration).where(PendingRegistration.email == email))
            if not pending:
                raise HTTPException(400, "Registration is incomplete.")
            workshop = Workshop(name=pending.workshop_name)
            db.add(workshop)
            db.flush()
            user = User(email=email, last_login_at=utcnow())
            db.add(user)
            db.flush()
            db.add(WorkshopUser(workshop_id=workshop.id, user_id=user.id, role="owner"))
            db.add(Branch(workshop_id=workshop.id, code="MAIN", name="Main Branch"))
            pending.verification_status = "completed"
        else:
            user.last_login_at = utcnow()
        db.flush()
        db.expunge(user)
        return user


def _ses():
    import boto3
    return boto3.client("sesv2", region_name=SES_REGION)


def _send_message(email: str, subject: str, body: str) -> bool:
    if EMAIL_PROVIDER == "ses":
        sender = os.getenv("INVENTORY_SES_FROM", "").strip()
        if not sender:
            logger.error("SES delivery is disabled because INVENTORY_SES_FROM is not configured")
            return False
        try:
            response = _ses().send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [email]},
                Content={"Simple": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}}},
            )
            logger.info("SES accepted %s email for %s; message_id=%s", subject, email, response.get("MessageId", "unknown"))
            return True
        except Exception:
            logger.exception("SES rejected %s email for %s", subject, email)
            return False
    if EMAIL_PROVIDER == "smtp":
        host = os.getenv("INVENTORY_SMTP_HOST", "")
        username = os.getenv("INVENTORY_SMTP_USERNAME", "")
        password = os.getenv("INVENTORY_SMTP_PASSWORD", "")
        sender = os.getenv("INVENTORY_SMTP_FROM", username)
        if not all((host, username, password, sender)):
            return False
        message = EmailMessage()
        message["Subject"], message["From"], message["To"] = subject, sender, email
        message.set_content(body)
        with smtplib.SMTP(host, int(os.getenv("INVENTORY_SMTP_PORT", "587"))) as smtp:
            smtp.starttls(); smtp.login(username, password); smtp.send_message(message)
        return True
    return False


def _send_verification_link(email: str, token: str) -> bool:
    link = f"{PUBLIC_BASE_URL}/api/auth/verify-email?token={token}"
    return _send_message(
        email,
        "Verify your WorkshopOS email",
        f"Welcome to WorkshopOS. Verify your email by opening this link within {VERIFICATION_TTL_HOURS} hours:\n\n{link}\n\nIf you did not request this, ignore this email.",
    )


def _send_otp(email: str, otp: str) -> bool:
    subject = "Your WorkshopOS sign-in code"
    body = f"Your WorkshopOS OTP is {otp}. It expires in {OTP_TTL_MINUTES} minutes."
    if EMAIL_PROVIDER in {"ses", "smtp"}:
        return _send_message(email, subject, body)
    print(f"[workshop-os] OTP for {email}: {otp}")
    return False
