from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import select, delete
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.push_subscription import PushSubscription
from app.security.deps import get_current_user

router = APIRouter(prefix="/push", tags=["push"])


class PushKeys(BaseModel):
    p256dh: str
    auth: str


class SubscribeRequest(BaseModel):
    endpoint: str
    keys: PushKeys


@router.get("/vapid-public-key")
def get_vapid_public_key():
    return {"publicKey": settings.vapid_public_key}


@router.post("/subscribe", status_code=201)
def subscribe(body: SubscribeRequest, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    # Upsert: if same endpoint exists (different user logged in same browser) update it
    existing = db.scalar(select(PushSubscription).where(PushSubscription.endpoint == body.endpoint))
    if existing:
        existing.user_id = current_user.id
        existing.p256dh = body.keys.p256dh
        existing.auth = body.keys.auth
    else:
        sub = PushSubscription(
            user_id=current_user.id,
            endpoint=body.endpoint,
            p256dh=body.keys.p256dh,
            auth=body.keys.auth,
        )
        db.add(sub)
    db.commit()
    return {"message": "subscribed"}


@router.post("/unsubscribe")
def unsubscribe(body: dict, db: Session = Depends(get_db), current_user=Depends(get_current_user)):
    endpoint = body.get("endpoint")
    if endpoint:
        db.execute(
            delete(PushSubscription).where(
                PushSubscription.endpoint == endpoint,
                PushSubscription.user_id == current_user.id,
            )
        )
        db.commit()
    return {"message": "unsubscribed"}
