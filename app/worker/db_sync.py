from collections.abc import Iterator
from contextlib import contextmanager

from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.config import get_settings

_engine: Engine | None = None
_sessionmaker: sessionmaker[Session] | None = None


def _sync_url(url: str) -> str:
    return url.replace("postgresql+asyncpg", "postgresql+psycopg2").replace(
        "sqlite+aiosqlite", "sqlite"
    )


def get_sync_engine() -> Engine:
    global _engine, _sessionmaker
    if _engine is None:
        settings = get_settings()
        _engine = create_engine(_sync_url(settings.database_url), future=True, pool_pre_ping=True)
        _sessionmaker = sessionmaker(_engine, expire_on_commit=False, autoflush=False)
    return _engine


def override_sync_sessionmaker(maker: sessionmaker[Session]) -> None:
    global _sessionmaker
    _sessionmaker = maker


@contextmanager
def sync_session_scope() -> Iterator[Session]:
    if _sessionmaker is None:
        get_sync_engine()
    assert _sessionmaker is not None
    with _sessionmaker() as session:
        yield session
