from sqlalchemy import ForeignKey, Integer, String, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class PostMedia(TimestampMixin, Base):
    __tablename__ = "post_media"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), nullable=False, index=True)
    file_url: Mapped[str] = mapped_column(Text, nullable=False)
    file_name: Mapped[str] = mapped_column(String(500), nullable=False)
    file_size: Mapped[int] = mapped_column(Integer, nullable=False)
    file_type: Mapped[str] = mapped_column(String(100), nullable=False)
    position: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
