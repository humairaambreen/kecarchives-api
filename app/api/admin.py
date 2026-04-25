from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import desc, func, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User, UserRole
from app.models.post import Post
from app.security.deps import get_current_user
from app.api.auth import _cleanup_user_media

router = APIRouter(prefix="/admin", tags=["admin"])


def _require_admin(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role != UserRole.admin:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Admin access required")
    return current_user


def _require_moderator(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in (UserRole.admin, UserRole.faculty):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Moderator access required")
    return current_user


class AdminUserOut(BaseModel):
    id: int
    full_name: str
    email: str
    role: str
    is_banned: bool
    avatar_base64: str | None = None
    banner_base64: str | None = None
    created_at: str | None = None
    username: str | None = None
    batch_year: int | None = None

    model_config = {"from_attributes": True}


class RoleUpdateRequest(BaseModel):
    role: str


class BanRequest(BaseModel):
    is_banned: bool


class BatchYearRequest(BaseModel):
    batch_year: int | None = None


class StatsOut(BaseModel):
    total_users: int
    students: int
    faculty: int
    guests: int
    banned: int
    total_posts: int


@router.get("/stats", response_model=StatsOut)
def admin_stats(db: Session = Depends(get_db), _admin: User = Depends(_require_admin)):
    total = db.scalar(select(func.count(User.id)).where(User.role != UserRole.admin)) or 0
    students = db.scalar(select(func.count(User.id)).where(User.role == UserRole.student)) or 0
    faculty = db.scalar(select(func.count(User.id)).where(User.role == UserRole.faculty)) or 0
    guests = db.scalar(select(func.count(User.id)).where(User.role == UserRole.guest)) or 0
    banned = db.scalar(select(func.count(User.id)).where(User.is_banned == True)) or 0  # noqa: E712
    total_posts = db.scalar(select(func.count(Post.id))) or 0

    return StatsOut(
        total_users=total,
        students=students,
        faculty=faculty,
        guests=guests,
        banned=banned,
        total_posts=total_posts,
    )


@router.get("/users", response_model=list[AdminUserOut])
def admin_list_users(db: Session = Depends(get_db), _admin: User = Depends(_require_admin)):
    users = db.scalars(
        select(User).where(User.role != UserRole.admin).order_by(desc(User.created_at))
    ).all()
    return [
        AdminUserOut(
            id=u.id,
            full_name=u.full_name,
            email=u.email,
            role=u.role.value if isinstance(u.role, UserRole) else u.role,
            is_banned=getattr(u, "is_banned", False) or False,
            avatar_base64=u.avatar_base64,
            banner_base64=u.banner_base64,
            created_at=str(u.created_at) if u.created_at else None,
            username=getattr(u, "username", None),
            batch_year=getattr(u, "batch_year", None),
        )
        for u in users
    ]


@router.patch("/users/{user_id}/role")
def admin_update_role(user_id: int, payload: RoleUpdateRequest, db: Session = Depends(get_db), _admin: User = Depends(_require_moderator)):
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == UserRole.admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot change admin role")
    try:
        new_role = UserRole(payload.role)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid role")
    # Strict hierarchy: only admin can assign faculty/admin roles
    if new_role == UserRole.admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot assign admin role")
    if new_role == UserRole.faculty and _admin.role not in (UserRole.admin, UserRole.faculty):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Only admin or faculty can assign faculty role")
    user.role = new_role
    db.commit()
    return {"message": "Role updated", "role": user.role.value}


@router.patch("/users/{user_id}/ban")
def admin_ban_user(user_id: int, payload: BanRequest, db: Session = Depends(get_db), _admin: User = Depends(_require_admin)):
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == UserRole.admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot ban admin")
    user.is_banned = payload.is_banned
    db.commit()
    return {"message": "User banned" if payload.is_banned else "User unbanned"}


@router.patch("/users/{user_id}/batch-year")
def admin_update_batch_year(user_id: int, payload: BatchYearRequest, db: Session = Depends(get_db), _admin: User = Depends(_require_moderator)):
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    user.batch_year = payload.batch_year
    db.commit()
    return {"message": "Batch year updated", "batch_year": user.batch_year}


@router.delete("/users/{user_id}")
def admin_delete_user(user_id: int, db: Session = Depends(get_db), _admin: User = Depends(_require_admin)):
    user = db.scalar(select(User).where(User.id == user_id))
    if not user:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")
    if user.role == UserRole.admin:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot delete admin")
    _cleanup_user_media(user.id, db)
    db.delete(user)
    db.commit()
    return {"message": "User deleted"}
