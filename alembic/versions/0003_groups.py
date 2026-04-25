"""add group chats

Revision ID: 0003_groups
Revises: 037cc9dc5eb9
Create Date: 2026-03-15
"""
from alembic import op
import sqlalchemy as sa

revision = "0003_groups"
down_revision = "037cc9dc5eb9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "group_chats",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("name", sa.String(80), nullable=False),
        sa.Column("description", sa.String(200), nullable=True),
        sa.Column("avatar_base64", sa.Text(), nullable=True),
        sa.Column("created_by", sa.Integer(), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
        sa.Column("invite_token", sa.String(64), unique=True, index=True, nullable=False),
        sa.Column("invite_enabled", sa.Boolean(), default=True, nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "group_memberships",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("group_chats.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("role", sa.String(20), nullable=False, server_default="member"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_membership"),
    )

    op.create_table(
        "group_messages",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("group_chats.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("sender_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("is_deleted", sa.Boolean(), default=False, nullable=False),
        sa.Column("is_edited", sa.Boolean(), default=False, nullable=False),
        sa.Column("reply_to_id", sa.Integer(), sa.ForeignKey("group_messages.id", ondelete="SET NULL"), nullable=True),
        sa.Column("file_url", sa.String(500), nullable=True),
        sa.Column("file_name", sa.String(255), nullable=True),
        sa.Column("file_size", sa.Integer(), nullable=True),
        sa.Column("file_type", sa.String(100), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
    )

    op.create_table(
        "group_invite_requests",
        sa.Column("id", sa.Integer(), primary_key=True, index=True),
        sa.Column("group_id", sa.Integer(), sa.ForeignKey("group_chats.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id", ondelete="CASCADE"), index=True, nullable=False),
        sa.Column("status", sa.String(20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), onupdate=sa.func.now()),
        sa.UniqueConstraint("group_id", "user_id", name="uq_group_invite_req"),
    )


def downgrade() -> None:
    op.drop_table("group_invite_requests")
    op.drop_table("group_messages")
    op.drop_table("group_memberships")
    op.drop_table("group_chats")
