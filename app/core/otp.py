"""OTP generation, storage, and email sending via Resend."""

import secrets
import time

import resend

from app.core.config import settings

# In-memory OTP store: { "purpose:email" -> (otp, expiry_ts) }
_otp_store: dict[str, tuple[str, float]] = {}

OTP_TTL = 600  # 10 minutes


def _generate_otp() -> str:
    return f"{secrets.randbelow(900000) + 100000}"


def _store_key(email: str, purpose: str) -> str:
    return f"{purpose}:{email.lower().strip()}"


def send_otp(email: str, purpose: str = "verify") -> None:
    """Generate (or use the bypass code) and store an OTP.

    If BYPASS_OTP is set in the environment, that fixed code is stored and
    no email is sent — useful for demos / when Resend is unavailable.
    """
    # ── Bypass mode ──────────────────────────────────────────────────────────
    if settings.bypass_otp:
        key = _store_key(email, purpose)
        _otp_store[key] = (settings.bypass_otp, time.time() + OTP_TTL)
        print(f"[OTP bypass] {purpose} for {email}: {settings.bypass_otp}")
        return

    # ── Normal mode ──────────────────────────────────────────────────────────
    otp = _generate_otp()
    key = _store_key(email, purpose)
    _otp_store[key] = (otp, time.time() + OTP_TTL)

    subject_map = {
        "verify": "Verify your KEC Archives account",
        "reset": "Reset your KEC Archives password",
        "admin": "Admin OTP for KEC Archives",
    }
    subject = subject_map.get(purpose, "Your OTP Code")

    html = f"""
    <div style="font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif; max-width: 400px; margin: 0 auto; padding: 32px 24px;">
        <h2 style="font-size: 20px; font-weight: 700; margin: 0 0 8px;">{subject}</h2>
        <p style="color: #666; font-size: 14px; margin: 0 0 24px;">Use this code to continue. It expires in 10 minutes.</p>
        <div style="background: #f5f5f5; border-radius: 12px; padding: 20px; text-align: center;">
            <span style="font-size: 32px; font-weight: 700; letter-spacing: 8px; color: #111;">{otp}</span>
        </div>
        <p style="color: #999; font-size: 12px; margin-top: 24px;">If you didn't request this, ignore this email.</p>
    </div>
    """

    if settings.resend_api_key:
        resend.api_key = settings.resend_api_key
        resend.Emails.send({
            "from": settings.email_from,
            "to": [email],
            "subject": subject,
            "html": html,
        })
    else:
        print(f"[OTP] {purpose} for {email}: {otp}")


def verify_otp(email: str, otp: str, purpose: str = "verify") -> bool:
    """Verify the OTP and consume it if valid.

    In bypass mode the fixed code is accepted without touching the in-memory
    store, so it works correctly on stateless serverless deployments (Vercel)
    where send and verify may run in different function instances.
    """
    if settings.bypass_otp:
        return secrets.compare_digest(otp.strip(), settings.bypass_otp)

    key = _store_key(email, purpose)
    entry = _otp_store.get(key)
    if not entry:
        return False
    stored_otp, expiry = entry
    if time.time() > expiry:
        _otp_store.pop(key, None)
        return False
    if not secrets.compare_digest(stored_otp, otp):
        return False
    _otp_store.pop(key, None)
    return True
