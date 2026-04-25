from sqlalchemy import ForeignKey, Integer, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Reaction(TimestampMixin, Base):
    __tablename__ = "reactions"
    __table_args__ = (UniqueConstraint("post_id", "user_id", "type", name="uq_reaction_post_user_type"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    type: Mapped[str] = mapped_column(String(32), default="like", nullable=False)
