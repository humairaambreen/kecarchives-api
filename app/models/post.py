from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Post(TimestampMixin, Base):
    __tablename__ = "posts"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    author_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)
    title: Mapped[str] = mapped_column(String(300), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    slug: Mapped[str] = mapped_column(String(350), unique=True, index=True, nullable=False)
    visibility: Mapped[str] = mapped_column(String(30), default="public", nullable=False)
    # Comma-separated batch years for batch_only posts
    target_batch_years_csv: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Comma-separated hashtags extracted from content
    tags_csv: Mapped[str | None] = mapped_column(Text, nullable=True)
    # Subject ID for subject_only posts
    subject_id: Mapped[int | None] = mapped_column(Integer, ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True, index=True)

    @property
    def target_batch_years(self) -> list[int]:
        if not self.target_batch_years_csv:
            return []
        return [int(y) for y in self.target_batch_years_csv.split(",") if y.strip()]

    @target_batch_years.setter
    def target_batch_years(self, years: list[int]) -> None:
        self.target_batch_years_csv = ",".join(str(y) for y in years) if years else None

    @property
    def tags(self) -> list[str]:
        if not self.tags_csv:
            return []
        return [t for t in self.tags_csv.split(",") if t.strip()]

    @tags.setter
    def tags(self, tag_list: list[str]) -> None:
        self.tags_csv = ",".join(tag_list) if tag_list else None


class SavedPost(TimestampMixin, Base):
    __tablename__ = "saved_posts"
    __table_args__ = (UniqueConstraint("user_id", "post_id", name="uq_saved_post"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    post_id: Mapped[int] = mapped_column(Integer, ForeignKey("posts.id", ondelete="CASCADE"), index=True)

