import json
import os
import uuid
from datetime import datetime, timezone, timedelta

import cloudinary
import cloudinary.uploader
import cloudinary.api
from fastapi import APIRouter, Depends, HTTPException, Query, UploadFile, File, Form, status

from pydantic import BaseModel, Field
from sqlalchemy import and_, delete, desc, or_, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.message import CallSession, Conversation, ConversationMessage, DMRequest, DMRequestStatus

MAX_FILE_SIZE = 50 * 1024 * 1024  # 50 MB

# Configure Cloudinary
cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
    secure=True,
)

from app.models.user import User
from app.security.deps import get_current_user
from app.services.notifications import create_notification

router = APIRouter(tags=["messages"])


# ── helpers ──

def _iso(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ── schemas ──

class UserMini(BaseModel):
    id: int
    full_name: str
    username: str | None = None
    avatar_base64: str | None = None


class MessageRequestOut(BaseModel):
    id: int
    from_user: UserMini
    to_user: UserMini
    context: str
    status: str
    created_at: str


class ConversationOut(BaseModel):
    id: int
    participant: UserMini
    last_message: str
    last_message_at: str
    unread: int = 0
    partner_is_typing: bool = False
    partner_last_read_msg_id: int | None = None


class ConversationMessageOut(BaseModel):
    id: int
    sender_id: int
    content: str
    created_at: str
    is_deleted: bool = False
    is_edited: bool = False
    reply_to_id: int | None = None
    file_url: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    file_type: str | None = None


class MessageRequestCreate(BaseModel):
    to_user_id: int
    context: str = Field(default="", max_length=500)


class MessageRequestUpdate(BaseModel):
    status: str = Field(pattern="^(accepted|rejected)$")


class SendMessagePayload(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    reply_to_id: int | None = None


class EditMessagePayload(BaseModel):
    content: str = Field(min_length=1, max_length=5000)


def _sorted_pair(a: int, b: int) -> tuple[int, int]:
    return (a, b) if a < b else (b, a)


# ── Message Requests ──

@router.get("/messages/requests", response_model=list[MessageRequestOut])
def list_requests(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    rows = db.scalars(
        select(DMRequest)
        .where(or_(DMRequest.to_user_id == current_user.id, DMRequest.from_user_id == current_user.id))
        .order_by(desc(DMRequest.created_at))
        .limit(100)
    ).all()

    user_ids = {r.from_user_id for r in rows} | {r.to_user_id for r in rows}
    users = db.scalars(select(User).where(User.id.in_(user_ids))).all() if user_ids else []
    users_map = {u.id: u for u in users}

    def _mini(uid: int) -> UserMini:
        u = users_map.get(uid)
        return UserMini(
            id=uid,
            full_name=u.full_name if u else "Unknown",
            username=u.username if u else None,
            avatar_base64=u.avatar_base64 if u else None,
        )

    return [
        MessageRequestOut(
            id=r.id,
            from_user=_mini(r.from_user_id),
            to_user=_mini(r.to_user_id),
            context=r.context,
            status=r.status.value if isinstance(r.status, DMRequestStatus) else str(r.status),
            created_at=_iso(r.created_at),
        )
        for r in rows
    ]


@router.post("/messages/requests", response_model=MessageRequestOut)
def create_request(
    payload: MessageRequestCreate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    if payload.to_user_id == current_user.id:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot message yourself")

    target = db.scalar(select(User).where(User.id == payload.to_user_id))
    if not target:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="User not found")

    existing = db.scalar(
        select(DMRequest).where(
            DMRequest.from_user_id == current_user.id,
            DMRequest.to_user_id == payload.to_user_id,
            DMRequest.status == DMRequestStatus.pending,
        )
    )
    if existing:
        return MessageRequestOut(
            id=existing.id,
            from_user=UserMini(id=current_user.id, full_name=current_user.full_name, username=current_user.username, avatar_base64=current_user.avatar_base64),
            to_user=UserMini(id=target.id, full_name=target.full_name, username=target.username, avatar_base64=target.avatar_base64),
            context=existing.context,
            status=existing.status.value,
            created_at=_iso(existing.created_at),
        )

    req = DMRequest(
        from_user_id=current_user.id,
        to_user_id=payload.to_user_id,
        context=payload.context.strip(),
        status=DMRequestStatus.pending,
    )
    db.add(req)
    db.commit()
    db.refresh(req)

    create_notification(
        db,
        user_id=payload.to_user_id,
        type="request",
        title=f"{current_user.full_name} sent a DM request",
        body=req.context or "Open Messages to accept or reject.",
        target_url="/messages",
    )

    return MessageRequestOut(
        id=req.id,
        from_user=UserMini(id=current_user.id, full_name=current_user.full_name, username=current_user.username, avatar_base64=current_user.avatar_base64),
        to_user=UserMini(id=target.id, full_name=target.full_name, username=target.username, avatar_base64=target.avatar_base64),
        context=req.context,
        status=req.status.value,
        created_at=_iso(req.created_at),
    )


@router.patch("/messages/requests/{request_id}")
def respond_request(
    request_id: int,
    payload: MessageRequestUpdate,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    req = db.scalar(select(DMRequest).where(DMRequest.id == request_id))
    if not req:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Request not found")
    if req.to_user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    req.status = DMRequestStatus(payload.status)
    db.commit()

    convo_id: int | None = None
    if req.status == DMRequestStatus.accepted:
        a, b = _sorted_pair(req.from_user_id, req.to_user_id)
        convo = db.scalar(select(Conversation).where(Conversation.user_a_id == a, Conversation.user_b_id == b))
        if not convo:
            convo = Conversation(user_a_id=a, user_b_id=b)
            db.add(convo)
            db.commit()
            db.refresh(convo)
        convo_id = convo.id

        create_notification(
            db,
            user_id=req.from_user_id,
            type="request",
            title="DM request accepted",
            body=f"{current_user.full_name} accepted your message request.",
            target_url="/messages",
        )
    else:
        create_notification(
            db,
            user_id=req.from_user_id,
            type="request",
            title="DM request rejected",
            body=f"{current_user.full_name} declined your message request.",
            target_url="/messages",
        )

    return {"message": "updated", "status": req.status.value, "conversation_id": convo_id}


# ── Conversations ──

def _convo_partner_fields(convo: Conversation, current_user_id: int):
    if convo.user_a_id == current_user_id:
        partner_id = convo.user_b_id
        typing_at = getattr(convo, "typing_at_b", None)
        last_read = getattr(convo, "last_read_msg_id_b", None)
    else:
        partner_id = convo.user_a_id
        typing_at = getattr(convo, "typing_at_a", None)
        last_read = getattr(convo, "last_read_msg_id_a", None)

    is_typing = False
    if typing_at:
        if isinstance(typing_at, str):
            try:
                typing_at = datetime.fromisoformat(typing_at)
            except ValueError:
                typing_at = None
        if typing_at:
            if typing_at.tzinfo is None:
                typing_at = typing_at.replace(tzinfo=timezone.utc)
            is_typing = (datetime.now(timezone.utc) - typing_at) < timedelta(seconds=5)

    return partner_id, is_typing, last_read


@router.get("/conversations", response_model=list[ConversationOut])
def list_conversations(db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    convos = db.scalars(
        select(Conversation)
        .where(or_(Conversation.user_a_id == current_user.id, Conversation.user_b_id == current_user.id))
        .order_by(desc(Conversation.updated_at))
        .limit(100)
    ).all()

    participant_ids: set[int] = set()
    for c in convos:
        participant_ids.add(c.user_b_id if c.user_a_id == current_user.id else c.user_a_id)
    users = db.scalars(select(User).where(User.id.in_(participant_ids))).all() if participant_ids else []
    user_map = {u.id: u for u in users}

    result: list[ConversationOut] = []
    for c in convos:
        partner_id, is_typing, last_read = _convo_partner_fields(c, current_user.id)
        participant = user_map.get(partner_id)
        last_message = db.scalar(
            select(ConversationMessage)
            .where(ConversationMessage.conversation_id == c.id)
            .order_by(desc(ConversationMessage.created_at))
            .limit(1)
        )
        result.append(
            ConversationOut(
                id=c.id,
                participant=UserMini(
                    id=partner_id,
                    full_name=participant.full_name if participant else "Unknown",
                    username=participant.username if participant else None,
                    avatar_base64=participant.avatar_base64 if participant else None,
                ),
                last_message=last_message.content if last_message else "Start chatting",
                last_message_at=_iso(last_message.created_at if last_message else c.created_at),
                unread=0,
                partner_is_typing=is_typing,
                partner_last_read_msg_id=last_read,
            )
        )
    return result


@router.get("/conversations/{conversation_id}/messages", response_model=list[ConversationMessageOut])
def list_messages(conversation_id: int, db: Session = Depends(get_db), current_user: User = Depends(get_current_user)):
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    rows = db.scalars(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(ConversationMessage.created_at.asc())
        .limit(500)
    ).all()

    return [
        ConversationMessageOut(
            id=row.id,
            sender_id=row.sender_id,
            content="This message was deleted" if getattr(row, "is_deleted", False) else row.content,
            created_at=_iso(row.created_at),
            is_deleted=getattr(row, "is_deleted", False),
            is_edited=getattr(row, "is_edited", False),
            reply_to_id=getattr(row, "reply_to_id", None),
            file_url=getattr(row, "file_url", None),
            file_name=getattr(row, "file_name", None),
            file_size=getattr(row, "file_size", None),
            file_type=getattr(row, "file_type", None),
        )
        for row in rows
    ]


@router.post("/conversations/{conversation_id}/messages", response_model=ConversationMessageOut)
def send_message(
    conversation_id: int,
    payload: SendMessagePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    msg = ConversationMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=payload.content.strip(),
        reply_to_id=payload.reply_to_id,
    )
    db.add(msg)

    # Clear typing indicator on send
    if convo.user_a_id == current_user.id:
        convo.typing_at_a = None
    else:
        convo.typing_at_b = None

    db.commit()
    db.refresh(msg)

    recipient_id = convo.user_b_id if current_user.id == convo.user_a_id else convo.user_a_id
    create_notification(
        db,
        user_id=recipient_id,
        type="message",
        title=f"New message from {current_user.full_name}",
        body=msg.content[:160],
        target_url="/messages",
    )

    return ConversationMessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        content=msg.content,
        created_at=_iso(msg.created_at),
        is_deleted=False,
        is_edited=False,
        reply_to_id=msg.reply_to_id,
    )


@router.delete("/conversations/{conversation_id}/messages/{message_id}")
def delete_message(
    conversation_id: int,
    message_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == message_id,
            ConversationMessage.conversation_id == conversation_id,
        )
    )
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only delete your own messages")

    msg.is_deleted = True
    msg.content = "This message was deleted"
    db.commit()
    return {"message": "deleted"}


@router.patch("/conversations/{conversation_id}/messages/{message_id}")
def edit_message(
    conversation_id: int,
    message_id: int,
    payload: EditMessagePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == message_id,
            ConversationMessage.conversation_id == conversation_id,
        )
    )
    if not msg:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Message not found")
    if msg.sender_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Can only edit your own messages")
    if getattr(msg, "is_deleted", False):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Cannot edit deleted message")

    msg.content = payload.content.strip()
    msg.is_edited = True
    db.commit()
    return {"message": "edited", "content": msg.content}


# ── Typing & Read ──

@router.post("/conversations/{conversation_id}/typing")
def set_typing(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    now = datetime.now(timezone.utc)
    if convo.user_a_id == current_user.id:
        convo.typing_at_a = now
    else:
        convo.typing_at_b = now
    db.commit()
    return {"ok": True}


@router.post("/conversations/{conversation_id}/read")
def mark_read(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    last_msg = db.scalar(
        select(ConversationMessage)
        .where(ConversationMessage.conversation_id == conversation_id)
        .order_by(desc(ConversationMessage.created_at))
        .limit(1)
    )
    if not last_msg:
        return {"ok": True}

    if convo.user_a_id == current_user.id:
        convo.last_read_msg_id_a = last_msg.id
    else:
        convo.last_read_msg_id_b = last_msg.id
    db.commit()
    return {"ok": True, "last_read_msg_id": last_msg.id}


@router.get("/conversations/{conversation_id}/info")
def get_conversation_info(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")

    _, is_typing, last_read = _convo_partner_fields(convo, current_user.id)
    return {
        "partner_is_typing": is_typing,
        "partner_last_read_msg_id": last_read,
    }


def _validate_convo_access(conversation_id: int, db: Session, current_user: User) -> Conversation:
    convo = db.scalar(select(Conversation).where(Conversation.id == conversation_id))
    if not convo:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Conversation not found")
    if current_user.id not in (convo.user_a_id, convo.user_b_id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Not allowed")
    return convo


# ── Message Search ──

@router.get("/conversations/{conversation_id}/messages/search", response_model=list[ConversationMessageOut])
def search_messages(
    conversation_id: int,
    q: str = Query(min_length=1, max_length=200),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_convo_access(conversation_id, db, current_user)

    rows = db.scalars(
        select(ConversationMessage)
        .where(
            ConversationMessage.conversation_id == conversation_id,
            ConversationMessage.content.ilike(f"%{q}%"),
            ConversationMessage.is_deleted == False,
        )
        .order_by(ConversationMessage.created_at.asc())
        .limit(50)
    ).all()

    return [
        ConversationMessageOut(
            id=row.id,
            sender_id=row.sender_id,
            content=row.content,
            created_at=_iso(row.created_at),
            is_deleted=False,
            is_edited=getattr(row, "is_edited", False),
            reply_to_id=getattr(row, "reply_to_id", None),
            file_url=getattr(row, "file_url", None),
            file_name=getattr(row, "file_name", None),
            file_size=getattr(row, "file_size", None),
            file_type=getattr(row, "file_type", None),
        )
        for row in rows
    ]


# ── File Upload (Cloudinary) ──

@router.post("/conversations/{conversation_id}/upload", response_model=ConversationMessageOut)
def upload_file(
    conversation_id: int,
    file: UploadFile = File(...),
    reply_to_id: int | None = Form(None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = _validate_convo_access(conversation_id, db, current_user)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No file provided")

    content = file.file.read()
    if len(content) > MAX_FILE_SIZE:
        raise HTTPException(status_code=400, detail="File too large (max 50 MB)")

    content_type = file.content_type or "application/octet-stream"
    is_image = content_type.startswith("image/")
    is_audio = content_type.startswith("audio/")
    is_video = content_type.startswith("video/")

    # Determine Cloudinary resource_type
    if is_image:
        resource_type = "image"
    elif is_video:
        resource_type = "video"
    else:
        resource_type = "raw"

    # Audio files → raw (Cloudinary "video" rejects formats like webm)
    if is_audio:
        resource_type = "raw"

    folder = f"kec_messages/{conversation_id}"

    try:
        import io
        result = cloudinary.uploader.upload(
            io.BytesIO(content),
            folder=folder,
            resource_type=resource_type,
            public_id=f"{uuid.uuid4().hex}",
        )
        file_url = result.get("secure_url", "")
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Upload failed: {str(e)}")

    label = "Shared a file"
    if is_audio:
        label = "Voice message" if "voice" in (file.filename or "").lower() else "Audio file"
    elif is_image:
        label = "Photo"

    msg = ConversationMessage(
        conversation_id=conversation_id,
        sender_id=current_user.id,
        content=label,
        reply_to_id=reply_to_id,
        file_url=file_url,
        file_name=file.filename,
        file_size=len(content),
        file_type=content_type,
    )
    db.add(msg)

    if convo.user_a_id == current_user.id:
        convo.typing_at_a = None
    else:
        convo.typing_at_b = None

    db.commit()
    db.refresh(msg)

    recipient_id = convo.user_b_id if current_user.id == convo.user_a_id else convo.user_a_id
    create_notification(
        db,
        user_id=recipient_id,
        type="message",
        title=f"{current_user.full_name} sent a file",
        body=file.filename or "File",
        target_url="/messages",
    )

    return ConversationMessageOut(
        id=msg.id,
        sender_id=msg.sender_id,
        content=msg.content,
        created_at=_iso(msg.created_at),
        is_deleted=False,
        is_edited=False,
        reply_to_id=msg.reply_to_id,
        file_url=msg.file_url,
        file_name=msg.file_name,
        file_size=msg.file_size,
        file_type=msg.file_type,
    )


class ForwardMessagePayload(BaseModel):
    target_conversation_id: int
    message_id: int


@router.post("/conversations/{conversation_id}/forward", response_model=ConversationMessageOut)
def forward_message(
    conversation_id: int,
    payload: ForwardMessagePayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    # Validate source conversation access
    src_convo = _validate_convo_access(conversation_id, db, current_user)

    # Get source message
    src_msg = db.scalar(
        select(ConversationMessage).where(
            ConversationMessage.id == payload.message_id,
            ConversationMessage.conversation_id == conversation_id,
        )
    )
    if not src_msg:
        raise HTTPException(status_code=404, detail="Message not found")
    if getattr(src_msg, "is_deleted", False):
        raise HTTPException(status_code=400, detail="Cannot forward a deleted message")

    # Validate target conversation access
    target_convo = _validate_convo_access(payload.target_conversation_id, db, current_user)

    # Build forwarded content
    content = src_msg.content
    if not getattr(src_msg, "file_url", None):
        content = f"↗ Forwarded\n{src_msg.content}"

    fwd = ConversationMessage(
        conversation_id=payload.target_conversation_id,
        sender_id=current_user.id,
        content=content if not getattr(src_msg, "file_url", None) else (f"↗ {src_msg.content}" if src_msg.content else "↗ Forwarded file"),
        file_url=getattr(src_msg, "file_url", None),
        file_name=getattr(src_msg, "file_name", None),
        file_size=getattr(src_msg, "file_size", None),
        file_type=getattr(src_msg, "file_type", None),
    )
    db.add(fwd)

    if target_convo.user_a_id == current_user.id:
        target_convo.typing_at_a = None
    else:
        target_convo.typing_at_b = None

    db.commit()
    db.refresh(fwd)

    recipient_id = target_convo.user_b_id if current_user.id == target_convo.user_a_id else target_convo.user_a_id
    create_notification(
        db,
        user_id=recipient_id,
        type="message",
        title=f"{current_user.full_name} sent a message",
        body=(fwd.content or "Forwarded message")[:160],
        target_url="/messages",
    )

    return ConversationMessageOut(
        id=fwd.id,
        sender_id=fwd.sender_id,
        content=fwd.content,
        created_at=_iso(fwd.created_at),
        is_deleted=False,
        is_edited=False,
        reply_to_id=None,
        file_url=fwd.file_url,
        file_name=fwd.file_name,
        file_size=fwd.file_size,
        file_type=fwd.file_type,
    )


# ── WebRTC Call Signaling ──

class CallStartPayload(BaseModel):
    call_type: str = Field(default="audio", pattern="^audio$")
    caller_peer_id: str


@router.post("/conversations/{conversation_id}/call/start")
def start_call(
    conversation_id: int,
    payload: CallStartPayload,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = _validate_convo_access(conversation_id, db, current_user)
    callee_id = convo.user_b_id if current_user.id == convo.user_a_id else convo.user_a_id

    # End any existing active calls
    active = db.scalars(
        select(CallSession).where(
            CallSession.conversation_id == conversation_id,
            CallSession.status.in_(["ringing", "active"]),
        )
    ).all()
    for c in active:
        c.status = "ended"
        c.ended_at = datetime.now(timezone.utc)
    db.flush()

    call = CallSession(
        conversation_id=conversation_id,
        caller_id=current_user.id,
        callee_id=callee_id,
        call_type=payload.call_type,
        status="ringing",
        offer_sdp=payload.caller_peer_id,  # reuse column to store PeerJS peer ID
    )
    db.add(call)
    db.commit()
    db.refresh(call)

    create_notification(
        db,
        user_id=callee_id,
        type="call",
        title="Incoming audio call",
        body=f"{current_user.full_name} is calling you",
        target_url=f"/messages/{convo.user_a_id if callee_id == convo.user_a_id else convo.user_b_id}",
    )

    return {"call_id": call.id, "status": "ringing"}


@router.post("/conversations/{conversation_id}/call/{call_id}/answer")
def answer_call(
    conversation_id: int,
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_convo_access(conversation_id, db, current_user)
    call = db.scalar(select(CallSession).where(CallSession.id == call_id, CallSession.conversation_id == conversation_id))
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")
    if call.callee_id != current_user.id:
        raise HTTPException(status_code=403, detail="Not the callee")

    call.status = "active"
    db.commit()
    return {"status": "active"}


@router.post("/conversations/{conversation_id}/call/{call_id}/end")
def end_call(
    conversation_id: int,
    call_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_convo_access(conversation_id, db, current_user)
    call = db.scalar(select(CallSession).where(CallSession.id == call_id, CallSession.conversation_id == conversation_id))
    if not call:
        raise HTTPException(status_code=404, detail="Call not found")

    call.status = "ended"
    call.ended_at = datetime.now(timezone.utc)
    db.commit()
    return {"status": "ended"}


@router.get("/conversations/{conversation_id}/call/active")
def get_active_call(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    _validate_convo_access(conversation_id, db, current_user)
    call = db.scalar(
        select(CallSession).where(
            CallSession.conversation_id == conversation_id,
            CallSession.status.in_(["ringing", "active"]),
        ).order_by(desc(CallSession.created_at)).limit(1)
    )
    if not call:
        return {"active": False}

    is_caller = current_user.id == call.caller_id
    return {
        "active": True,
        "call_id": call.id,
        "call_type": call.call_type,
        "status": call.status,
        "is_caller": is_caller,
        "caller_peer_id": call.offer_sdp,
        "caller_id": call.caller_id,
        "callee_id": call.callee_id,
    }


# ── Delete entire conversation ──────────────────────────────────────
@router.delete("/conversations/{conversation_id}")
def delete_conversation(
    conversation_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    convo = _validate_convo_access(conversation_id, db, current_user)
    other_user_id = convo.user_b_id if convo.user_a_id == current_user.id else convo.user_a_id

    # Delete Cloudinary folder for this conversation
    try:
        prefix = f"kec_messages/{conversation_id}"
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

    # Delete the conversation row (CASCADE deletes messages + call sessions)
    db.delete(convo)

    # Also remove any DM request between these two users
    db.execute(
        delete(DMRequest).where(
            or_(
                and_(DMRequest.from_user_id == current_user.id, DMRequest.to_user_id == other_user_id),
                and_(DMRequest.from_user_id == other_user_id, DMRequest.to_user_id == current_user.id),
            )
        )
    )

    db.commit()
    return {"deleted": True}

