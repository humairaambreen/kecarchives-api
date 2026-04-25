import logging

from sqlalchemy.orm import Session

from app.models.notification import Notification

logger = logging.getLogger(__name__)


def create_notification(
    db: Session,
    *,
    user_id: int,
    type: str,
    title: str,
    body: str,
    target_url: str | None = None,
) -> Notification:
    notification = Notification(
        user_id=user_id,
        type=type,
        title=title,
        body=body,
        target_url=target_url,
        read=False,
    )
    db.add(notification)
    db.commit()
    db.refresh(notification)
    return notification
