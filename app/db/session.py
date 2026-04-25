from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import NullPool

from app.core.config import settings


_is_sqlite = settings.database_url.startswith("sqlite")
connect_args = {"check_same_thread": False} if _is_sqlite else {"sslmode": "require"}

# In serverless (Vercel), each function invocation is a fresh process.
# NullPool avoids stale connections and removes pool overhead — the actual
# connection reuse happens inside Supabase's PgBouncer, not here.
engine = create_engine(
    settings.database_url,
    future=True,
    pool_pre_ping=_is_sqlite,   # sqlite needs this; Postgres handled by PgBouncer
    connect_args=connect_args,
    **({"poolclass": NullPool} if not _is_sqlite else {}),
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()