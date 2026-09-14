from __future__ import annotations

import base64
import hashlib
import hmac
import json
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
SECRET = os.getenv("INVENTORY_SECRET_KEY", "local-dev-change-me")
COOKIE_SECURE = os.getenv("INVENTORY_COOKIE_SECURE", "false").lower() == "true"
DEV_RETURN_OTP = os.getenv("INVENTORY_DEV_RETURN_OTP", "true").lower() == "true"
EMAIL_PROVIDER = os.getenv("INVENTORY_EMAIL_PROVIDER", "console").strip().lower()
SES_REGION = os.getenv("INVENTORY_SES_REGION", os.getenv("AWS_REGION", "ap-south-1"))
EMAIL_PATTERN = re.compile(r"^(?=.{6,254}$)(?!.*\.\.)[A-Z0-9.!#$%&'*+/=?^_`{|}~-]+@(?:[A-Z0-9](?:[A-Z0-9-]{0,61}[A-Z0-9])?\.)+[A-Z]{2,63}$", re.I)

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


def session_token(email: str) -> str:
    return _signed({"email": normalize_email(email), "iat": int(time.time())})


def session_email(token: str | None) -> str | None:
    if not token:
        return None
    try:
        raw, signature = token.split(".", 1)
        expected = hmac.new(SECRET.encode(), raw.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(signature, expected):
            return None
        payload = json.loads(base64.urlsafe_b64decode((raw + "=" * (-len(raw) % 4)).encode()))
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

    if EMAIL_PROVIDER == "ses":
        try:
            response = _ses().get_email_identity(EmailIdentity=email)
            status = str(response.get("VerificationStatus") or "NOT_STARTED")
            if status.upper() != "SUCCESS":
                _ses().create_email_identity(EmailIdentity=email)
                status = "PENDING"
        except Exception as exc:
            raise HTTPException(503, f"Unable to request the verification email: {exc}") from exc
    else:
        status = "SUCCESS"

    with SessionLocal.begin() as db:
        record = db.scalar(select(EmailVerification).where(EmailVerification.email == email))
        detail = "AWS SES verification link requested." if EMAIL_PROVIDER == "ses" else "Local verification completed."
        if record:
            record.status, record.provider, record.detail = status, EMAIL_PROVIDER, detail
            record.verified_at = utcnow() if status == "SUCCESS" else None
        else:
            db.add(EmailVerification(email=email, status=status, provider=EMAIL_PROVIDER, detail=detail, verified_at=utcnow() if status == "SUCCESS" else None))
    return {
        "status": "verified" if status == "SUCCESS" else "pending",
        "email": email,
        "message": "Verification email sent. Click its link, then request an OTP." if status != "SUCCESS" else "Email verified. Request an OTP to sign in.",
    }


def request_otp(email: str) -> dict:
    email = validate_email(email)
    with SessionLocal.begin() as db:
        user = db.scalar(select(User).where(User.email == email))
        verification = db.scalar(select(EmailVerification).where(EmailVerification.email == email))
        if EMAIL_PROVIDER == "ses" and not user:
            try:
                status = str(_ses().get_email_identity(EmailIdentity=email).get("VerificationStatus") or "NOT_STARTED")
            except Exception as exc:
                raise HTTPException(503, "Unable to check email verification status.") from exc
            if status.upper() != "SUCCESS":
                raise HTTPException(403, "Email is not verified. Use New workshop registration and click the verification link first.")
            if verification:
                verification.status, verification.verified_at = "SUCCESS", utcnow()
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


def _send_otp(email: str, otp: str) -> bool:
    subject = "Your WorkshopOS sign-in code"
    body = f"Your WorkshopOS OTP is {otp}. It expires in {OTP_TTL_MINUTES} minutes."
    if EMAIL_PROVIDER == "ses":
        # A fixed verified domain is preferred. During a low-cost SES pilot the
        # newly verified recipient identity can also send its own OTP.
        sender = os.getenv("INVENTORY_SES_FROM", "").strip() or email
        try:
            _ses().send_email(
                FromEmailAddress=sender,
                Destination={"ToAddresses": [email]},
                Content={"Simple": {"Subject": {"Data": subject}, "Body": {"Text": {"Data": body}}}},
            )
            return True
        except Exception:
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
    print(f"[workshop-os] OTP for {email}: {otp}")
    return False
