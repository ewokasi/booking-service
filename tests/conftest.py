import os
import tempfile
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import pytest
import pytest_asyncio

_TMP_DB = Path(tempfile.mkdtemp(prefix="booking-tests-")) / "test.db"
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP_DB}"
os.environ["ALEMBIC_DATABASE_URL"] = f"sqlite:///{_TMP_DB}"
os.environ["CELERY_BROKER_URL"] = "memory://"
os.environ["CELERY_RESULT_BACKEND"] = "cache+memory://"
os.environ["CELERY_TASK_ALWAYS_EAGER"] = "true"
os.environ["RATE_LIMIT_CREATE_BOOKING"] = "10000/minute"
os.environ["WORKER_FAILURE_RATE"] = "0.0"
os.environ["WORKER_MAX_RETRIES"] = "2"
os.environ["WORKER_RETRY_BACKOFF"] = "1"
os.environ["LOG_LEVEL"] = "WARNING"

from httpx import ASGITransport, AsyncClient  # noqa: E402
from sqlalchemy import create_engine  # noqa: E402
from sqlalchemy.ext.asyncio import (  # noqa: E402
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import sessionmaker  # noqa: E402

import app.models  # noqa: E402,F401
from app import db as app_db  # noqa: E402
from app.config import get_settings  # noqa: E402
from app.db import Base  # noqa: E402
from app.main import create_app  # noqa: E402
from app.worker import db_sync as worker_db  # noqa: E402


@pytest.fixture(scope="session")
def db_path() -> Path:
    return _TMP_DB


@pytest.fixture(scope="session")
def sync_engine(db_path: Path):
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return engine


@pytest.fixture(scope="session")
def async_engine(db_path: Path, sync_engine):
    return create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)


@pytest.fixture(autouse=True)
def _wire_sessions(sync_engine, async_engine) -> Iterator[None]:
    sync_maker = sessionmaker(sync_engine, expire_on_commit=False, autoflush=False)
    async_maker = async_sessionmaker(async_engine, expire_on_commit=False)
    app_db.override_sessionmaker(async_maker)
    worker_db.override_sync_sessionmaker(sync_maker)

    with sync_engine.begin() as conn:
        for table in reversed(Base.metadata.sorted_tables):
            conn.exec_driver_sql(f"DELETE FROM {table.name}")
    yield


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    get_settings.cache_clear()
    app = create_app()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as c:
        yield c
