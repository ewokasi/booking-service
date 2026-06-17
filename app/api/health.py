import asyncio

from fastapi import APIRouter, Request, Response, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.db import session_scope
from app.logging import get_logger

router = APIRouter(tags=["meta"])
log = get_logger(__name__)

_PROBE_TIMEOUT_SECONDS = 3.0


@router.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}


async def _ping_postgres() -> None:
    async with session_scope() as session:
        await session.execute(text("SELECT 1"))


async def _ping_redis(client: Redis) -> None:
    await client.ping()


@router.get("/readyz")
async def readyz(request: Request, response: Response) -> dict[str, object]:
    checks: dict[str, str] = {}
    ok = True

    try:
        await asyncio.wait_for(_ping_postgres(), timeout=_PROBE_TIMEOUT_SECONDS)
        checks["postgres"] = "ok"
    except TimeoutError:
        ok = False
        checks["postgres"] = "error: TimeoutError"
        log.warning("readyz_postgres_timeout", timeout=_PROBE_TIMEOUT_SECONDS)
    except Exception as exc:
        ok = False
        checks["postgres"] = f"error: {exc.__class__.__name__}"
        log.warning("readyz_postgres_failed", error=str(exc))

    redis_client: Redis | None = getattr(request.app.state, "redis", None)
    if redis_client is None:
        ok = False
        checks["redis"] = "error: NotInitialized"
    else:
        try:
            await asyncio.wait_for(_ping_redis(redis_client), timeout=_PROBE_TIMEOUT_SECONDS)
            checks["redis"] = "ok"
        except TimeoutError:
            ok = False
            checks["redis"] = "error: TimeoutError"
            log.warning("readyz_redis_timeout", timeout=_PROBE_TIMEOUT_SECONDS)
        except Exception as exc:
            ok = False
            checks["redis"] = f"error: {exc.__class__.__name__}"
            log.warning("readyz_redis_failed", error=str(exc))

    response.status_code = status.HTTP_200_OK if ok else status.HTTP_503_SERVICE_UNAVAILABLE
    return {"status": "ok" if ok else "degraded", "checks": checks}
