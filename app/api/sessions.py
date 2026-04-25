from fastapi import APIRouter, Depends
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.session import Session as UserSession
from app.models.user import User
from app.schemas.session import SessionOut
from app.security.deps import get_current_user

router = APIRouter(prefix="/account", tags=["account-security"])


@router.get("/sessions", response_model=list[SessionOut])
def list_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    sessions = db.scalars(
        select(UserSession)
        .where(UserSession.user_id == current_user.id)
        .order_by(desc(UserSession.last_active_at))
        .limit(50)
    ).all()
    return sessions


@router.delete("/sessions/{session_id}")
def revoke_session(session_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    db.query(UserSession).filter(UserSession.id == session_id, UserSession.user_id == current_user.id).delete()
    db.commit()
    return {"message": "Session revoked"}


@router.post("/sessions/revoke-others")
def revoke_other_sessions(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    deleted = db.query(UserSession).filter(UserSession.user_id == current_user.id).delete()
    db.commit()
    return {"message": "Other sessions revoked", "deleted": deleted}
