import enum

from sqlalchemy import Enum, Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin


class UserRole(str, enum.Enum):
    guest = "guest"
    student = "student"
    faculty = "faculty"
    admin = "admin"


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True, index=True)
    username: Mapped[str | None] = mapped_column(String(40), unique=True, index=True, nullable=True)
    full_name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(254), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    avatar_base64: Mapped[str | None] = mapped_column(String, nullable=True)
    banner_base64: Mapped[str | None] = mapped_column(String, nullable=True)
    bio: Mapped[str | None] = mapped_column(String(500), nullable=True)
    role: Mapped[UserRole] = mapped_column(Enum(UserRole), default=UserRole.guest, nullable=False)
    is_banned: Mapped[bool] = mapped_column(default=False, nullable=False)
    batch_year: Mapped[int | None] = mapped_column(Integer, nullable=True)
