from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Comment(TimestampMixin, Base):
    __tablename__ = "comments"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), index=True)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    parent_comment_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("comments.id", ondelete="SET NULL"), nullable=True, index=True)
    content: Mapped[str] = mapped_column(Text, nullable=False)
