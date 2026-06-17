import uuid
from datetime import datetime

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Booking, BookingStatus


class BookingNotFoundError(Exception):
    pass


class BookingNotCancellableError(Exception):
    pass


async def create_booking(
    session: AsyncSession,
    *,
    name: str,
    when: datetime,
    service_type: str,
) -> Booking:
    booking = Booking(
        name=name,
        datetime=when,
        service_type=service_type,
        status=BookingStatus.pending,
    )
    session.add(booking)
    await session.commit()
    await session.refresh(booking)
    return booking


async def get_booking(session: AsyncSession, booking_id: uuid.UUID) -> Booking:
    booking = await session.get(Booking, booking_id)
    if booking is None:
        raise BookingNotFoundError(str(booking_id))
    return booking


async def list_bookings(
    session: AsyncSession,
    *,
    status: BookingStatus | None,
    limit: int,
    offset: int,
) -> tuple[list[Booking], int]:
    base = select(Booking)
    count_q = select(func.count()).select_from(Booking)
    if status is not None:
        base = base.where(Booking.status == status)
        count_q = count_q.where(Booking.status == status)

    base = base.order_by(Booking.created_at.desc()).limit(limit).offset(offset)
    items = (await session.execute(base)).scalars().all()
    total = (await session.execute(count_q)).scalar_one()
    return list(items), int(total)


async def cancel_booking(session: AsyncSession, booking_id: uuid.UUID) -> None:
    result = await session.execute(
        delete(Booking).where(
            Booking.id == booking_id,
            Booking.status == BookingStatus.pending,
        )
    )
    if result.rowcount == 1:
        await session.commit()
        return

    current = await session.execute(
        select(Booking.status).where(Booking.id == booking_id)
    )
    status = current.scalar_one_or_none()
    if status is None:
        raise BookingNotFoundError(str(booking_id))
    raise BookingNotCancellableError(status.value)
