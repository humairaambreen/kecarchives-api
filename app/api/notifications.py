from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.notification import Notification
from app.security.deps import get_current_user

router = APIRouter(prefix="/notifications", tags=["notifications"])


class NotificationOut(BaseModel):
    id: int
    type: str
    title: str
    body: str
    read: bool = False
    target_url: str | None = None
    created_at: str


def _map_notification(item: Notification) -> NotificationOut:
    return NotificationOut(
        id=item.id,
        type=item.type,
        title=item.title,
        body=item.body,
        read=item.read,
        target_url=item.target_url,
        created_at=str(item.created_at) if item.created_at else "",
    )


@router.get("", response_model=list[NotificationOut])
def list_notifications(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    items = db.scalars(
        select(Notification)
        .where(Notification.user_id == current_user.id)
        .order_by(desc(Notification.created_at))
        .limit(100)
    ).all()
    return [_map_notification(item) for item in items]


@router.post("/{notification_id}/read")
def mark_read(notification_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    item = db.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
    )
    if item:
        item.read = True
        db.commit()
    return {"message": "ok", "notification_id": notification_id}


@router.post("/read-all")
def mark_all_read(db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    rows = db.scalars(select(Notification).where(Notification.user_id == current_user.id, Notification.read == False)).all()  # noqa: E712
    for row in rows:
        row.read = True
    db.commit()
    return {"message": "ok"}


@router.delete("/{notification_id}")
def delete_notification(notification_id: int, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    item = db.scalar(
        select(Notification).where(Notification.id == notification_id, Notification.user_id == current_user.id)
    )
    if item:
        db.delete(item)
        db.commit()
    return {"message": "ok", "notification_id": notification_id}
