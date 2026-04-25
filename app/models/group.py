import secrets
from typing import Optional

from sqlalchemy import Boolean, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class GroupChat(TimestampMixin, Base):
    __tablename__ = "group_chats"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(80), nullable=False)
    description: Mapped[Optional[str]] = mapped_column(String(200), nullable=True)
    avatar_base64: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
    invite_token: Mapped[str] = mapped_column(String(64), unique=True, index=True, default=lambda: secrets.token_urlsafe(32))
    invite_enabled: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    auto_approve: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)


class GroupMembership(TimestampMixin, Base):
    __tablename__ = "group_memberships"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_membership"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("group_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    role: Mapped[str] = mapped_column(String(20), default="member", nullable=False)  # "admin" | "member"


class GroupMessage(TimestampMixin, Base):
    __tablename__ = "group_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("group_chats.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reply_to_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("group_messages.id", ondelete="SET NULL"), nullable=True)
    file_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    file_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True)


class GroupInviteRequest(TimestampMixin, Base):
    """Pending invite-link join requests awaiting admin approval."""
    __tablename__ = "group_invite_requests"
    __table_args__ = (UniqueConstraint("group_id", "user_id", name="uq_group_invite_req"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    group_id: Mapped[int] = mapped_column(Integer, ForeignKey("group_chats.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    status: Mapped[str] = mapped_column(String(20), default="pending", nullable=False)  # "pending" | "approved" | "rejected"
