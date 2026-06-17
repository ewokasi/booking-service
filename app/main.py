from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from redis.asyncio import Redis
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from app.api.bookings import router as bookings_router
from app.api.health import router as health_router
from app.config import get_settings
from app.logging import configure_logging, get_logger
from app.rate_limit import limiter


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    configure_logging()
    settings = get_settings()
    app.state.redis = Redis.from_url(
        settings.redis_url,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    get_logger(__name__).info("app_startup")
    try:
        yield
    finally:
        await app.state.redis.aclose()
        get_logger(__name__).info("app_shutdown")


def create_app() -> FastAPI:
    app = FastAPI(
        title="Booking Service",
        version="0.1.0",
        lifespan=lifespan,
    )
    app.state.limiter = limiter
    app.add_middleware(SlowAPIMiddleware)

    from slowapi import _rate_limit_exceeded_handler

    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

    app.include_router(health_router)
    app.include_router(bookings_router)

    return app


app = create_app()
