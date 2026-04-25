import secrets
from datetime import datetime, timezone

import cloudinary
import cloudinary.uploader
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from pydantic import BaseModel, Field
from sqlalchemy import desc, select
from sqlalchemy.orm import Session

from app.core.config import settings
from app.db.session import get_db
from app.models.group import GroupChat, GroupInviteRequest, GroupMembership, GroupMessage
from app.models.user import User
from app.security.deps import get_current_user, get_current_user_optional

cloudinary.config(
    cloud_name=settings.cloudinary_cloud_name,
    api_key=settings.cloudinary_api_key,
    api_secret=settings.cloudinary_api_secret,
    secure=True,
)

router = APIRouter(prefix="/groups", tags=["groups"])

MAX_FILE_SIZE = 50 * 1024 * 1024


def _iso(dt: datetime | None) -> str:
    if dt is None:
        return datetime.now(timezone.utc).isoformat()
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


# ── Schemas ───────────────────────────────────────────────────────────────────

class MemberOut(BaseModel):
    user_id: int
    full_name: str
    username: str | None = None
    avatar_base64: str | None = None
    role: str


class GroupOut(BaseModel):
    id: int
    name: str
    description: str | None = None
    avatar_base64: str | None = None
    invite_token: str
    invite_enabled: bool
    auto_approve: bool = False
    member_count: int
    my_role: str | None = None
    last_message: str = ""
    last_message_at: str = ""
    created_at: str


class GroupMessageOut(BaseModel):
    id: int
    group_id: int
    sender_id: int
    sender_name: str
    sender_username: str | None = None
    sender_avatar: str | None = None
    content: str
    is_deleted: bool
    is_edited: bool
    reply_to_id: int | None = None
    file_url: str | None = None
    file_name: str | None = None
    file_size: int | None = None
    file_type: str | None = None
    created_at: str


class CreateGroupPayload(BaseModel):
    name: str = Field(min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=200)


class UpdateGroupPayload(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=80)
    description: str | None = Field(default=None, max_length=200)
    invite_enabled: bool | None = None
    auto_approve: bool | None = None


class SendGroupMessagePayload(BaseModel):
    content: str = Field(min_length=1, max_length=5000)
    reply_to_id: int | None = None


class UpdateMemberPayload(BaseModel):
    role: str = Field(pattern="^(admin|member)$")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _require_member(group_id: int, user_id: int, db: Session) -> GroupMembership:
    m = db.scalar(select(GroupMembership).where(
        GroupMembership.group_id == group_id, GroupMembership.user_id == user_id
    ))
    if not m:
        raise HTTPException(status_code=403, detail="Not a member of this group")
    return m


def _require_admin(group_id: int, user_id: int, db: Session) -> GroupMembership:
    m = _require_member(group_id, user_id, db)
    if m.role != "admin":
        raise HTTPException(status_code=403, detail="Group admin access required")
    return m


def _build_group_out(g: GroupChat, user_id: int, db: Session) -> GroupOut:
    members = db.scalars(select(GroupMembership).where(GroupMembership.group_id == g.id)).all()
    my_m = next((m for m in members if m.user_id == user_id), None)
    last = db.scalar(select(GroupMessage).where(GroupMessage.group_id == g.id).order_by(desc(GroupMessage.created_at)))
    return GroupOut(
        id=g.id, name=g.name, description=g.description, avatar_base64=g.avatar_base64,
        invite_token=g.invite_token, invite_enabled=g.invite_enabled, auto_approve=g.auto_approve,
        member_count=len(members),
        my_role=my_m.role if my_m else None,
        last_message=last.content if last and not last.is_deleted else ("" if not last else "Message deleted"),
        last_message_at=_iso(last.created_at) if last else _iso(g.created_at),
        created_at=_iso(g.created_at),
    )


def _msg_out(msg: GroupMessage, sender: User) -> GroupMessageOut:
    return GroupMessageOut(
        id=msg.id, group_id=msg.group_id, sender_id=msg.sender_id,
        sender_name=sender.full_name, sender_username=sender.username, sender_avatar=sender.avatar_base64,
        content=msg.content, is_deleted=msg.is_deleted, is_edited=msg.is_edited,
        reply_to_id=msg.reply_to_id, file_url=msg.file_url, file_name=msg.file_name,
        file_size=msg.file_size, file_type=msg.file_type, created_at=_iso(msg.created_at),
    )


# ── CRUD ──────────────────────────────────────────────────────────────────────

@router.post("", response_model=GroupOut, status_code=201)
def create_group(payload: CreateGroupPayload, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    g = GroupChat(name=payload.name, description=payload.description, created_by=me.id,
                  invite_token=secrets.token_urlsafe(32))
    db.add(g); db.flush()
    db.add(GroupMembership(group_id=g.id, user_id=me.id, role="admin"))
    db.commit(); db.refresh(g)
    return _build_group_out(g, me.id, db)


@router.get("", response_model=list[GroupOut])
def list_my_groups(db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    memberships = db.scalars(select(GroupMembership).where(GroupMembership.user_id == me.id)).all()
    gids = [m.group_id for m in memberships]
    if not gids: return []
    groups = db.scalars(select(GroupChat).where(GroupChat.id.in_(gids))).all()
    return sorted([_build_group_out(g, me.id, db) for g in groups], key=lambda x: x.last_message_at, reverse=True)


@router.get("/invite/{token}")
def get_group_by_invite(token: str, db: Session = Depends(get_db), me: User | None = Depends(get_current_user_optional)):
    g = db.scalar(select(GroupChat).where(GroupChat.invite_token == token))
    if not g:
        raise HTTPException(status_code=404, detail="Invite link not found")
    if not g.invite_enabled:
        raise HTTPException(status_code=403, detail="Invite link has been disabled")
    members = db.scalars(select(GroupMembership).where(GroupMembership.group_id == g.id)).all()
    already_member = any(m.user_id == me.id for m in members) if me else False
    pending = False
    if me and not already_member:
        req = db.scalar(select(GroupInviteRequest).where(
            GroupInviteRequest.group_id == g.id,
            GroupInviteRequest.user_id == me.id,
            GroupInviteRequest.status == "pending",
        ))
        pending = req is not None
    return {
        "id": g.id, "name": g.name, "description": g.description,
        "avatar_base64": g.avatar_base64, "member_count": len(members),
        "already_member": already_member, "pending_approval": pending,
    }


@router.post("/invite/{token}/join", status_code=201)
def join_via_invite(token: str, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    g = db.scalar(select(GroupChat).where(GroupChat.invite_token == token))
    if not g or not g.invite_enabled:
        raise HTTPException(status_code=404, detail="Invalid or disabled invite link")
    existing = db.scalar(select(GroupMembership).where(
        GroupMembership.group_id == g.id, GroupMembership.user_id == me.id
    ))
    if existing:
        return {"status": "already_member", "group_id": g.id}
    # Auto-approve: add directly as member, no request needed
    if g.auto_approve:
        db.add(GroupMembership(group_id=g.id, user_id=me.id, role="member"))
        db.commit()
        return {"status": "joined", "group_id": g.id}
    # Check for existing pending request
    dup = db.scalar(select(GroupInviteRequest).where(
        GroupInviteRequest.group_id == g.id,
        GroupInviteRequest.user_id == me.id,
        GroupInviteRequest.status == "pending",
    ))
    if dup:
        return {"status": "pending_approval", "group_id": g.id}
    req = GroupInviteRequest(group_id=g.id, user_id=me.id, status="pending")
    db.add(req); db.commit()
    return {"status": "pending_approval", "group_id": g.id}


@router.get("/{group_id}", response_model=GroupOut)
def get_group(group_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    g = db.scalar(select(GroupChat).where(GroupChat.id == group_id))
    if not g: raise HTTPException(404, "Group not found")
    _require_member(group_id, me.id, db)
    return _build_group_out(g, me.id, db)


@router.patch("/{group_id}", response_model=GroupOut)
def update_group(group_id: int, payload: UpdateGroupPayload, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    g = db.scalar(select(GroupChat).where(GroupChat.id == group_id))
    if not g: raise HTTPException(404, "Group not found")
    _require_admin(group_id, me.id, db)
    if payload.name is not None: g.name = payload.name
    if payload.description is not None: g.description = payload.description
    if payload.invite_enabled is not None: g.invite_enabled = payload.invite_enabled
    if payload.auto_approve is not None: g.auto_approve = payload.auto_approve
    db.commit(); db.refresh(g)
    return _build_group_out(g, me.id, db)


@router.post("/{group_id}/avatar", response_model=GroupOut)
async def update_avatar(group_id: int, avatar_base64: str = Form(...), db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    g = db.scalar(select(GroupChat).where(GroupChat.id == group_id))
    if not g: raise HTTPException(404, "Group not found")
    _require_admin(group_id, me.id, db)
    g.avatar_base64 = avatar_base64
    db.commit(); db.refresh(g)
    return _build_group_out(g, me.id, db)


@router.post("/{group_id}/reset-invite", response_model=GroupOut)
def reset_invite_link(group_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    g = db.scalar(select(GroupChat).where(GroupChat.id == group_id))
    if not g: raise HTTPException(404, "Group not found")
    _require_admin(group_id, me.id, db)
    g.invite_token = secrets.token_urlsafe(32)
    db.commit(); db.refresh(g)
    return _build_group_out(g, me.id, db)


@router.delete("/{group_id}", status_code=204)
def delete_group(group_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    g = db.scalar(select(GroupChat).where(GroupChat.id == group_id))
    if not g: raise HTTPException(404, "Group not found")
    _require_admin(group_id, me.id, db)
    db.delete(g); db.commit()


# ── Members ───────────────────────────────────────────────────────────────────

@router.get("/{group_id}/members", response_model=list[MemberOut])
def list_members(group_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_member(group_id, me.id, db)
    memberships = db.scalars(select(GroupMembership).where(GroupMembership.group_id == group_id)).all()
    uids = [m.user_id for m in memberships]
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(uids))).all()}
    return [MemberOut(user_id=m.user_id, full_name=users[m.user_id].full_name,
                      username=users[m.user_id].username, avatar_base64=users[m.user_id].avatar_base64,
                      role=m.role) for m in memberships if m.user_id in users]


@router.post("/{group_id}/members", status_code=201)
def add_member(group_id: int, body: dict, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_admin(group_id, me.id, db)
    user_id = body.get("user_id")
    if not user_id: raise HTTPException(400, "user_id required")
    target = db.scalar(select(User).where(User.id == user_id))
    if not target: raise HTTPException(404, "User not found")
    dup = db.scalar(select(GroupMembership).where(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id))
    if dup: raise HTTPException(400, "Already a member")
    db.add(GroupMembership(group_id=group_id, user_id=user_id, role="member"))
    db.commit()
    return {"ok": True}


@router.patch("/{group_id}/members/{user_id}")
def update_member_role(group_id: int, user_id: int, payload: UpdateMemberPayload, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_admin(group_id, me.id, db)
    if user_id == me.id: raise HTTPException(400, "Cannot change your own role")
    m = db.scalar(select(GroupMembership).where(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id))
    if not m: raise HTTPException(404, "Member not found")
    m.role = payload.role; db.commit()
    return {"ok": True, "role": m.role}


@router.delete("/{group_id}/members/{user_id}", status_code=204)
def remove_member(group_id: int, user_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    my_m = _require_member(group_id, me.id, db)
    if user_id != me.id and my_m.role != "admin":
        raise HTTPException(403, "Only admins can remove others")
    m = db.scalar(select(GroupMembership).where(GroupMembership.group_id == group_id, GroupMembership.user_id == user_id))
    if not m: raise HTTPException(404, "Member not found")
    db.delete(m); db.commit()


# ── Invite requests ───────────────────────────────────────────────────────────

@router.get("/{group_id}/requests")
def list_join_requests(group_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_admin(group_id, me.id, db)
    reqs = db.scalars(select(GroupInviteRequest).where(
        GroupInviteRequest.group_id == group_id, GroupInviteRequest.status == "pending"
    )).all()
    uids = [r.user_id for r in reqs]
    users = {u.id: u for u in db.scalars(select(User).where(User.id.in_(uids))).all()}
    return [{"id": r.id, "user_id": r.user_id,
             "full_name": users[r.user_id].full_name if r.user_id in users else "Unknown",
             "username": users[r.user_id].username if r.user_id in users else None,
             "avatar_base64": users[r.user_id].avatar_base64 if r.user_id in users else None,
             "created_at": _iso(r.created_at)} for r in reqs]


@router.post("/{group_id}/requests/{request_id}")
def respond_to_request(group_id: int, request_id: int, body: dict, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_admin(group_id, me.id, db)
    action = body.get("action")  # "approve" | "reject"
    req = db.scalar(select(GroupInviteRequest).where(GroupInviteRequest.id == request_id, GroupInviteRequest.group_id == group_id))
    if not req: raise HTTPException(404, "Request not found")
    if action == "approve":
        req.status = "approved"
        dup = db.scalar(select(GroupMembership).where(GroupMembership.group_id == group_id, GroupMembership.user_id == req.user_id))
        if not dup:
            db.add(GroupMembership(group_id=group_id, user_id=req.user_id, role="member"))
    elif action == "reject":
        req.status = "rejected"
    else:
        raise HTTPException(400, "action must be 'approve' or 'reject'")
    db.commit()
    return {"ok": True}


# ── Messages ──────────────────────────────────────────────────────────────────

@router.get("/{group_id}/messages", response_model=list[GroupMessageOut])
def get_messages(group_id: int, limit: int = 100, before_id: int | None = None, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_member(group_id, me.id, db)
    q = select(GroupMessage).where(GroupMessage.group_id == group_id)
    if before_id: q = q.where(GroupMessage.id < before_id)
    msgs = db.scalars(q.order_by(desc(GroupMessage.created_at)).limit(limit)).all()
    msgs = list(reversed(msgs))
    sids = {m.sender_id for m in msgs}
    senders = {u.id: u for u in db.scalars(select(User).where(User.id.in_(sids))).all()}
    return [_msg_out(m, senders[m.sender_id]) for m in msgs if m.sender_id in senders]


@router.post("/{group_id}/messages", response_model=GroupMessageOut, status_code=201)
def send_message(group_id: int, payload: SendGroupMessagePayload, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_member(group_id, me.id, db)
    msg = GroupMessage(group_id=group_id, sender_id=me.id, content=payload.content, reply_to_id=payload.reply_to_id)
    db.add(msg); db.commit(); db.refresh(msg)
    return _msg_out(msg, me)


@router.delete("/{group_id}/messages/{msg_id}", status_code=204)
def delete_message(group_id: int, msg_id: int, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_member(group_id, me.id, db)
    msg = db.scalar(select(GroupMessage).where(GroupMessage.id == msg_id, GroupMessage.group_id == group_id))
    if not msg: raise HTTPException(404, "Message not found")
    my_m = db.scalar(select(GroupMembership).where(GroupMembership.group_id == group_id, GroupMembership.user_id == me.id))
    if msg.sender_id != me.id and (not my_m or my_m.role != "admin"):
        raise HTTPException(403, "Not authorized")
    msg.is_deleted = True; msg.content = "This message was deleted"; db.commit()


@router.patch("/{group_id}/messages/{msg_id}", response_model=GroupMessageOut)
def edit_message(group_id: int, msg_id: int, body: dict, db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_member(group_id, me.id, db)
    msg = db.scalar(select(GroupMessage).where(GroupMessage.id == msg_id, GroupMessage.group_id == group_id))
    if not msg or msg.is_deleted: raise HTTPException(404, "Message not found")
    if msg.sender_id != me.id: raise HTTPException(403, "Can only edit your own messages")
    content = body.get("content", "").strip()
    if not content: raise HTTPException(400, "Content required")
    msg.content = content; msg.is_edited = True; db.commit(); db.refresh(msg)
    return _msg_out(msg, me)


@router.post("/{group_id}/upload", response_model=GroupMessageOut, status_code=201)
async def upload_file(group_id: int, file: UploadFile = File(...), reply_to_id: int | None = Form(None), db: Session = Depends(get_db), me: User = Depends(get_current_user)):
    _require_member(group_id, me.id, db)
    content = await file.read()
    if len(content) > MAX_FILE_SIZE: raise HTTPException(400, "File too large (max 50 MB)")
    ct = file.content_type or "application/octet-stream"
    rtype = "image" if ct.startswith("image/") else "video" if ct.startswith("video/") else "raw"
    import io
    result = cloudinary.uploader.upload(io.BytesIO(content), folder=f"kec_groups/{group_id}", resource_type=rtype)
    msg = GroupMessage(group_id=group_id, sender_id=me.id, content=file.filename or "file",
                       reply_to_id=reply_to_id, file_url=result.get("secure_url"),
                       file_name=file.filename, file_size=len(content), file_type=ct)
    db.add(msg); db.commit(); db.refresh(msg)
    return _msg_out(msg, me)