import cloudinary
import cloudinary.api

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User
from app.models.message import Conversation
from app.schemas.auth import (
    AdminLoginRequest,
    AdminOtpRequest,
    ForgotPasswordRequest,
    LoginRequest,
    RefreshRequest,
    RegisterRequest,
    ResetPasswordRequest,
    ResetPasswordWithOtpRequest,
    SendOtpRequest,
    TokenPair,
    UpdateProfileRequest,
    UsernameCheckRequest,
    UserProfile,
    VerifyOtpRequest,
)
from app.core.config import settings
from app.core.otp import send_otp as _send_otp, verify_otp as _verify_otp
from app.security.deps import get_current_user
from app.security.hash import hash_password, verify_password
from app.security.tokens import create_access_token, create_refresh_token, decode_refresh_token


router = APIRouter(prefix="/auth", tags=["auth"])


# ── OTP endpoints ──────────────────────────────────────────────────────

@router.post("/send-otp")
def send_otp_endpoint(payload: SendOtpRequest):
    """Send a 6-digit OTP to the given email."""
    _send_otp(payload.email, payload.purpose)
    return {"message": "OTP sent"}


@router.post("/verify-otp")
def verify_otp_endpoint(payload: VerifyOtpRequest):
    """Verify an OTP (for the 'verify' purpose). Consumed on success."""
    if not _verify_otp(payload.email, payload.otp, "verify"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")
    return {"verified": True}


# ── Registration (OTP-verified) ────────────────────────────────────────

@router.post("/register", response_model=TokenPair)
def register(payload: RegisterRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.email == payload.email.lower()))
    if existing:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Email already registered")

    existing_username = db.scalar(select(User).where(User.username == payload.username.lower()))
    if existing_username:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")

    user = User(
        full_name=payload.full_name,
        username=payload.username.lower(),
        email=payload.email.lower(),
        password_hash=hash_password(payload.password),
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/login", response_model=TokenPair)
def login(payload: LoginRequest, db: Session = Depends(get_db)):
    identifier = payload.identifier.lower().strip()
    # Try email or username
    user = db.scalar(
        select(User).where(
            or_(User.email == identifier, User.username == identifier)
        )
    )
    if not user or not verify_password(payload.password, user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account has been banned")

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/logout")
def logout():
    return {"message": "Logged out"}


@router.post("/refresh", response_model=TokenPair)
def refresh_tokens(payload: RefreshRequest, db: Session = Depends(get_db)):
    """Exchange a valid refresh token for a fresh access + refresh token pair."""
    user_id = decode_refresh_token(payload.refresh_token)
    if user_id is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired refresh token")

    user = db.scalar(select(User).where(User.id == int(user_id)))
    if user is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="User not found")
    if user.is_banned:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Your account has been banned")

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/forgot-password")
def forgot_password(payload: ForgotPasswordRequest, db: Session = Depends(get_db)):
    """Send a reset OTP to the user's email."""
    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    # Always return success to prevent email enumeration
    if user:
        _send_otp(payload.email, "reset")
    return {"message": "If the account exists, an OTP has been sent."}


@router.post("/reset-password")
def reset_password(payload: ResetPasswordWithOtpRequest, db: Session = Depends(get_db)):
    """Reset password using email + OTP."""
    if not _verify_otp(payload.email, payload.otp, "reset"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")

    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    user.password_hash = hash_password(payload.new_password)
    db.commit()
    return {"message": "Password updated."}


@router.get("/search", response_model=list[UserProfile])
def search_users(q: str = "", db: Session = Depends(get_db)):
    if not q or len(q) < 1:
        return []
    term = f"%{q}%"
    results = db.scalars(
        select(User).where(
            (User.full_name.ilike(term)) | (User.email.ilike(term)) | (User.username.ilike(term))
        ).limit(20)
    ).all()
    return results


@router.get("/me", response_model=UserProfile)
def get_me(current_user: User = Depends(get_current_user)):
    return current_user


@router.post("/check-admin")
def check_admin(payload: ForgotPasswordRequest):
    if settings.admin_email and payload.email.lower() == settings.admin_email.lower():
        return {"is_admin_email": True}
    return {"is_admin_email": False}


@router.post("/admin-login")
def admin_login(payload: AdminLoginRequest):
    if not settings.admin_email or payload.email.lower() != settings.admin_email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin email")
    if not settings.admin_password or payload.password != settings.admin_password:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid admin password")
    # Send OTP via Resend
    _send_otp(payload.email, "admin")
    return {"success": True}


@router.post("/verify-admin-otp", response_model=TokenPair)
def verify_admin_otp(payload: AdminOtpRequest, db: Session = Depends(get_db)):
    if not settings.admin_email or payload.email.lower() != settings.admin_email.lower():
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not an admin email")
    if not _verify_otp(payload.email, payload.otp, "admin"):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or expired OTP")

    from app.models.user import UserRole

    user = db.scalar(select(User).where(User.email == payload.email.lower()))
    if not user:
        user = User(
            full_name="Admin",
            username="admin",
            email=payload.email.lower(),
            password_hash=hash_password(settings.admin_password or "admin"),
            role=UserRole.admin,
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        user.role = UserRole.admin
        db.commit()

    access = create_access_token(str(user.id))
    refresh = create_refresh_token(str(user.id))
    return TokenPair(access_token=access, refresh_token=refresh)


@router.post("/check-username")
def check_username(payload: UsernameCheckRequest, db: Session = Depends(get_db)):
    existing = db.scalar(select(User).where(User.username == payload.username.lower()))
    return {"available": existing is None}


@router.get("/profile/{user_id}", response_model=UserProfile)
def get_profile(user_id: int, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.get("/profile/by-username/{username}", response_model=UserProfile)
def get_profile_by_username(username: str, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == username.lower()))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    return user


@router.patch("/me", response_model=UserProfile)
def update_me(payload: UpdateProfileRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    current_user.full_name = payload.full_name
    if "bio" in payload.model_fields_set:
        current_user.bio = payload.bio
    if "username" in payload.model_fields_set and payload.username:
        new_username = payload.username.lower()
        if new_username != current_user.username:
            existing = db.scalar(select(User).where(User.username == new_username))
            if existing:
                raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Username already taken")
            current_user.username = new_username
    current_user.avatar_base64 = payload.avatar_base64
    current_user.banner_base64 = payload.banner_base64
    db.commit()
    db.refresh(current_user)
    return current_user


class DeleteAccountRequest(BaseModel):
    password: str


def _cleanup_user_media(user_id: int, db: Session):
    """Delete all Cloudinary media from the user's conversations."""
    convos = db.scalars(
        select(Conversation).where(
            or_(Conversation.user_a_id == user_id, Conversation.user_b_id == user_id)
        )
    ).all()
    for convo in convos:
        try:
            prefix = f"kec_messages/{convo.id}"
            for resource_type in ("image", "video", "raw"):
                try:
                    cloudinary.api.delete_resources_by_prefix(prefix, resource_type=resource_type)
                except Exception:
                    pass
            try:
                cloudinary.api.delete_folder(prefix)
            except Exception:
                pass
        except Exception:
            pass


@router.delete("/me")
def delete_my_account(payload: DeleteAccountRequest, current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    if not verify_password(payload.password, current_user.password_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Incorrect password")

    _cleanup_user_media(current_user.id, db)
    db.delete(current_user)
    db.commit()
    return {"message": "Account deleted"}
