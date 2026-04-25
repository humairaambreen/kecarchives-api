from fastapi import FastAPI, Response
from fastapi.middleware.cors import CORSMiddleware

from app.api.router import api_router
from app.core.config import settings
from app.db.session import engine
from app.db import base  # noqa: F401
from app.models.base import Base


def _ensure_sqlite_profile_columns() -> None:
    if not settings.database_url.startswith("sqlite"):
        return

    with engine.begin() as conn:
        rows = conn.exec_driver_sql("PRAGMA table_info(users)").fetchall()
        existing_columns = {row[1] for row in rows}
        if "avatar_base64" not in existing_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN avatar_base64 TEXT")
        if "banner_base64" not in existing_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN banner_base64 TEXT")
        if "is_banned" not in existing_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN is_banned BOOLEAN DEFAULT 0 NOT NULL")
        if "bio" not in existing_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN bio TEXT")
        if "username" not in existing_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN username TEXT")
        if "batch_year" not in existing_columns:
            conn.exec_driver_sql("ALTER TABLE users ADD COLUMN batch_year INTEGER")

        tables = {
            row[0] for row in conn.exec_driver_sql("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }

        if "comments" in tables:
            comment_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(comments)").fetchall()
            }
            if "parent_comment_id" not in comment_columns:
                conn.exec_driver_sql("ALTER TABLE comments ADD COLUMN parent_comment_id INTEGER")

        if "notifications" in tables:
            notification_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(notifications)").fetchall()
            }
            if "target_url" not in notification_columns:
                conn.exec_driver_sql("ALTER TABLE notifications ADD COLUMN target_url TEXT")

        if "conversation_messages" in tables:
            msg_columns = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(conversation_messages)").fetchall()
            }
            if "is_deleted" not in msg_columns:
                conn.exec_driver_sql("ALTER TABLE conversation_messages ADD COLUMN is_deleted BOOLEAN DEFAULT 0 NOT NULL")
            if "is_edited" not in msg_columns:
                conn.exec_driver_sql("ALTER TABLE conversation_messages ADD COLUMN is_edited BOOLEAN DEFAULT 0 NOT NULL")
            if "reply_to_id" not in msg_columns:
                conn.exec_driver_sql("ALTER TABLE conversation_messages ADD COLUMN reply_to_id INTEGER")
            if "file_url" not in msg_columns:
                conn.exec_driver_sql("ALTER TABLE conversation_messages ADD COLUMN file_url TEXT")
            if "file_name" not in msg_columns:
                conn.exec_driver_sql("ALTER TABLE conversation_messages ADD COLUMN file_name TEXT")
            if "file_size" not in msg_columns:
                conn.exec_driver_sql("ALTER TABLE conversation_messages ADD COLUMN file_size INTEGER")
            if "file_type" not in msg_columns:
                conn.exec_driver_sql("ALTER TABLE conversation_messages ADD COLUMN file_type TEXT")

        # Ensure post_media table exists
        if "post_media" not in tables:
            conn.exec_driver_sql("""
                CREATE TABLE post_media (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    post_id INTEGER NOT NULL REFERENCES posts(id) ON DELETE CASCADE,
                    file_url TEXT NOT NULL,
                    file_name VARCHAR(500) NOT NULL,
                    file_size INTEGER NOT NULL,
                    file_type VARCHAR(100) NOT NULL,
                    position INTEGER NOT NULL DEFAULT 0,
                    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
            """)
            conn.exec_driver_sql("CREATE INDEX IF NOT EXISTS ix_post_media_post_id ON post_media(post_id)")


def _ensure_group_columns() -> None:
    """Add new columns to group_chats that may not exist in older DBs (works for both SQLite + Postgres)."""
    from sqlalchemy import text, inspect as sa_inspect
    with engine.connect() as conn:
        try:
            inspector = sa_inspect(engine)
            if "group_chats" not in inspector.get_table_names():
                return  # table doesn't exist yet — create_all will handle it
            existing = {col["name"] for col in inspector.get_columns("group_chats")}
            if "auto_approve" not in existing:
                conn.execute(text("ALTER TABLE group_chats ADD COLUMN auto_approve BOOLEAN NOT NULL DEFAULT FALSE"))
                conn.commit()
        except Exception:
            pass  # column may already exist in a concurrent startup


def create_app() -> FastAPI:
    app = FastAPI(title="KEC Archives API", version="0.1.0")

    # Schema setup: only run expensive create_all on SQLite (local dev).
    # In production (Postgres/Supabase) the schema already exists — running
    # create_all on every cold start adds 8-15 s of SSL + schema-inspection
    # overhead which causes Vercel's 10 s function timeout to fire on every poll.
    if settings.database_url.startswith("sqlite"):
        Base.metadata.create_all(bind=engine)
        _ensure_sqlite_profile_columns()
    else:
        # Production: only create tables that are genuinely new (push_subscriptions etc.)
        # by using checkfirst=True — much faster than a full reflect.
        Base.metadata.create_all(bind=engine, checkfirst=True)
    _ensure_group_columns()

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.get("/health", tags=["health"])
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", tags=["health"])
    def root() -> dict[str, str]:
        return {"service": "KEC Archives API", "status": "ok", "docs": "/docs"}

    @app.get("/sw.js", tags=["health"])
    def service_worker_probe() -> Response:
        return Response(status_code=204)

    app.include_router(api_router, prefix="/api/v1")
    return app


app = create_app()