"""add subjects and subject_enrollments tables, subject_id on posts

Revision ID: 0002_subjects
Revises: 0001_initial
Create Date: 2026-03-14
"""

from alembic import op
import sqlalchemy as sa


revision = "0002_subjects"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # Create subjects table
    op.create_table(
        "subjects",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(120), nullable=False),
        sa.Column("code", sa.String(30), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
    )
    op.create_index("ix_subjects_id", "subjects", ["id"], unique=False)
    op.create_index("ix_subjects_code", "subjects", ["code"], unique=True)

    # Create subject_enrollments table
    op.create_table(
        "subject_enrollments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id", ondelete="CASCADE"), nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="student"),
        sa.Column("assigned_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("subject_id", "user_id", name="uq_subject_enrollment"),
    )
    op.create_index("ix_subject_enrollments_subject_id", "subject_enrollments", ["subject_id"])
    op.create_index("ix_subject_enrollments_user_id", "subject_enrollments", ["user_id"])

    # Add subject_id column to posts
    op.add_column(
        "posts",
        sa.Column("subject_id", sa.Integer(), sa.ForeignKey("subjects.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_index("ix_posts_subject_id", "posts", ["subject_id"])


def downgrade() -> None:
    op.drop_index("ix_posts_subject_id", table_name="posts")
    op.drop_column("posts", "subject_id")

    op.drop_index("ix_subject_enrollments_user_id", table_name="subject_enrollments")
    op.drop_index("ix_subject_enrollments_subject_id", table_name="subject_enrollments")
    op.drop_table("subject_enrollments")

    op.drop_index("ix_subjects_code", table_name="subjects")
    op.drop_index("ix_subjects_id", table_name="subjects")
    op.drop_table("subjects")
