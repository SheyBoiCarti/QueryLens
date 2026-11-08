"""Database engine and connection management for metadata store."""

from __future__ import annotations

from contextlib import contextmanager
from typing import Generator
import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

from querylens.config import get_settings
from querylens.persistence.tables import metadata

_engine: Engine | None = None


def get_engine(db_url: str | None = None) -> Engine:
    """Get or create singleton metadata database engine."""
    global _engine
    if _engine is None or db_url is not None:
        url = db_url or get_settings().metadata_database_url
        # If url is postgresql, ensure psycopg driver
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql+psycopg://", 1)
        elif url.startswith("postgresql://") and not url.startswith("postgresql+psycopg://"):
            url = url.replace("postgresql://", "postgresql+psycopg://", 1)

        # Engine configuration
        if "sqlite" in url:
            engine = sa.create_engine(url, echo=False)
        else:
            settings = get_settings()
            engine = sa.create_engine(
                url,
                pool_size=5,
                max_overflow=5,
                pool_timeout=settings.pool_acquire_timeout_sec,
                connect_args={
                    "connect_timeout": max(1, int(settings.connect_timeout_sec)),
                    "options": f"-c statement_timeout={max(1, int(settings.cleanup_timeout_sec * 1000))}",
                },
                pool_pre_ping=True,
                echo=False,
            )
        if db_url is None:
            _engine = engine
        return engine
    return _engine


def set_engine(engine: Engine | None) -> None:
    """Override singleton engine (for testing)."""
    global _engine
    _engine = engine


def create_metadata_tables(engine: Engine | None = None) -> None:
    """Create all metadata tables using DDL."""
    eng = engine or get_engine()
    metadata.create_all(bind=eng)


def drop_metadata_tables(engine: Engine | None = None) -> None:
    """Drop all metadata tables."""
    eng = engine or get_engine()
    metadata.drop_all(bind=eng)


@contextmanager
def get_db_connection(engine: Engine | None = None) -> Generator[Connection, None, None]:
    """Yield a transactional database connection."""
    eng = engine or get_engine()
    with eng.begin() as conn:
        yield conn
