import os
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.orm import declarative_base, sessionmaker

# Local Postgres install created during setup: superuser 'postgres', database
# 'infinity_mart'. Override via DATABASE_URL for a different environment
# (Docker, a managed Postgres instance, etc.) without touching code.
DATABASE_URL = os.environ.get(
    "DATABASE_URL",
    "postgresql+psycopg2://postgres:infinity_mart_dev@localhost:5432/infinity_mart",
)

engine = create_engine(DATABASE_URL, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

Base = declarative_base()


@contextmanager
def session_scope():
    """Preferred way to touch the database through the ORM: guarantees the
    session is committed-and-closed (or rolled-back-and-closed on error) even
    if the caller raises partway through."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


@contextmanager
def connection():
    """Raw connection for analytics queries (pandas read_sql_query, ad-hoc
    joins/aggregates) that are more naturally expressed as SQL than ORM
    queries. Same commit/rollback/close guarantee as session_scope()."""
    conn = engine.connect()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def init_schema():
    # Importing models registers every mapped class's table on Base.metadata
    # before create_all() runs, without models.py needing to import schema
    # first (which would be a circular import).
    import models  # noqa: F401

    Base.metadata.create_all(engine)
