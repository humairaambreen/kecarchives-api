from sqlalchemy import ForeignKey, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class Subject(TimestampMixin, Base):
    """A subject/course created by admin and managed by faculty."""
    __tablename__ = "subjects"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    code: Mapped[str] = mapped_column(String(30), unique=True, index=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False)


class SubjectEnrollment(TimestampMixin, Base):
    """Tracks who is enrolled in a subject (faculty or students)."""
    __tablename__ = "subject_enrollments"
    __table_args__ = (UniqueConstraint("subject_id", "user_id", name="uq_subject_enrollment"),)

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    subject_id: Mapped[int] = mapped_column(Integer, ForeignKey("subjects.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="CASCADE"), index=True)
    # "faculty" | "student" — role within the subject
    role: Mapped[str] = mapped_column(String(20), default="student", nullable=False)
    # who assigned this user (admin assigns faculty, faculty assigns students)
    assigned_by: Mapped[int] = mapped_column(Integer, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)
