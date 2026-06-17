import uuid

import anyio
from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db import get_session
from app.logging import get_logger
from app.models import BookingStatus
from app.rate_limit import limiter
from app.schemas import BookingCreate, BookingList, BookingRead
from app.services.bookings import (
    BookingNotCancellableError,
    BookingNotFoundError,
    cancel_booking,
    create_booking,
    get_booking,
    list_bookings,
)

router = APIRouter(prefix="/bookings", tags=["bookings"])
log = get_logger(__name__)


async def _enqueue_confirm(booking_id: uuid.UUID) -> None:
    from app.worker.tasks import confirm_booking

    await anyio.to_thread.run_sync(confirm_booking.delay, str(booking_id))


def _create_rate_limit(*_args: object, **_kwargs: object) -> str:
    return get_settings().rate_limit_create_booking


@router.post(
    "",
    response_model=BookingRead,
    status_code=status.HTTP_202_ACCEPTED,
)
@limiter.limit(_create_rate_limit)
async def create_booking_endpoint(
    request: Request,
    payload: BookingCreate,
    session: AsyncSession = Depends(get_session),
) -> BookingRead:
    booking = await create_booking(
        session,
        name=payload.name,
        when=payload.datetime,
        service_type=payload.service_type,
    )
    await _enqueue_confirm(booking.id)
    log.info("booking_created", booking_id=str(booking.id), service_type=booking.service_type)
    return BookingRead.model_validate(booking)


@router.get("/{booking_id}", response_model=BookingRead)
async def get_booking_endpoint(
    booking_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> BookingRead:
    try:
        booking = await get_booking(session, booking_id)
    except BookingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="booking not found") from exc
    return BookingRead.model_validate(booking)


@router.get("", response_model=BookingList)
async def list_bookings_endpoint(
    status_filter: BookingStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=20, ge=1, le=100),
    offset: int = Query(default=0, ge=0),
    session: AsyncSession = Depends(get_session),
) -> BookingList:
    items, total = await list_bookings(session, status=status_filter, limit=limit, offset=offset)
    return BookingList(
        items=[BookingRead.model_validate(b) for b in items],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.delete("/{booking_id}", status_code=status.HTTP_204_NO_CONTENT)
async def cancel_booking_endpoint(
    booking_id: uuid.UUID,
    session: AsyncSession = Depends(get_session),
) -> Response:
    try:
        await cancel_booking(session, booking_id)
    except BookingNotFoundError as exc:
        raise HTTPException(status_code=404, detail="booking not found") from exc
    except BookingNotCancellableError as exc:
        raise HTTPException(
            status_code=409, detail=f"booking not in pending status (got {exc})"
        ) from exc
    return Response(status_code=status.HTTP_204_NO_CONTENT)
