import enum
from datetime import datetime
from typing import Optional

from sqlalchemy import Boolean, DateTime, Enum, ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class DMRequestStatus(str, enum.Enum):
    pending = "pending"
    accepted = "accepted"
    rejected = "rejected"


class DMRequest(TimestampMixin, Base):
    __tablename__ = "dm_requests"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    from_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    to_user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    context: Mapped[str] = mapped_column(String(500), default="", nullable=False)
    status: Mapped[DMRequestStatus] = mapped_column(Enum(DMRequestStatus), default=DMRequestStatus.pending, nullable=False)


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"
    __table_args__ = (UniqueConstraint("user_a_id", "user_b_id", name="uq_conversation_pair"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_a_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    user_b_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    last_read_msg_id_a: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    last_read_msg_id_b: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    typing_at_a: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=None)
    typing_at_b: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True, default=None)


class ConversationMessage(TimestampMixin, Base):
    __tablename__ = "conversation_messages"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    sender_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    is_deleted: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    is_edited: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    reply_to_id: Mapped[Optional[int]] = mapped_column(Integer, ForeignKey("conversation_messages.id", ondelete="SET NULL"), nullable=True, default=None)
    file_url: Mapped[Optional[str]] = mapped_column(String(500), nullable=True, default=None)
    file_name: Mapped[Optional[str]] = mapped_column(String(255), nullable=True, default=None)
    file_size: Mapped[Optional[int]] = mapped_column(Integer, nullable=True, default=None)
    file_type: Mapped[Optional[str]] = mapped_column(String(100), nullable=True, default=None)


class CallSession(TimestampMixin, Base):
    __tablename__ = "call_sessions"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    conversation_id: Mapped[int] = mapped_column(Integer, ForeignKey("conversations.id", ondelete="CASCADE"), index=True)
    caller_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    callee_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"))
    call_type: Mapped[str] = mapped_column(String(10), default="audio")
    status: Mapped[str] = mapped_column(String(20), default="ringing")
    offer_sdp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    answer_sdp: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    caller_ice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    callee_ice: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    ended_at: Mapped[Optional[datetime]] = mapped_column(DateTime(timezone=True), nullable=True)
