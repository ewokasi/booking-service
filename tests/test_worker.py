import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy.orm import sessionmaker

from app.models import Booking, BookingStatus
from app.worker import tasks as worker_tasks


@pytest.fixture
def make_booking(sync_engine):
    maker = sessionmaker(sync_engine, expire_on_commit=False, autoflush=False)

    def _create(status: BookingStatus = BookingStatus.pending) -> uuid.UUID:
        booking = Booking(
            name="Bob",
            datetime=datetime.now(UTC) + timedelta(days=1),
            service_type="massage",
            status=status,
        )
        with maker() as session:
            session.add(booking)
            session.commit()
            session.refresh(booking)
            return booking.id

    return _create


def _get_status(sync_engine, booking_id: uuid.UUID) -> BookingStatus:
    maker = sessionmaker(sync_engine, expire_on_commit=False, autoflush=False)
    with maker() as session:
        return session.get(Booking, booking_id).status  # type: ignore[union-attr]


def test_worker_confirms_when_no_failure(
    sync_engine, make_booking, monkeypatch
) -> None:
    monkeypatch.setattr(worker_tasks, "_roll_failure", lambda rate: False)
    sent: list[tuple[str, str, str]] = []
    monkeypatch.setattr(
        worker_tasks,
        "send_notification",
        lambda bid, name, st: sent.append((bid, name, st)),
    )

    booking_id = make_booking()
    result = worker_tasks.confirm_booking.apply(args=[str(booking_id)]).get()

    assert result == "confirmed"
    assert _get_status(sync_engine, booking_id) == BookingStatus.confirmed
    assert sent == [(str(booking_id), "Bob", "massage")]


def test_worker_marks_failed_after_retries_exhausted(
    sync_engine, make_booking, monkeypatch
) -> None:
    monkeypatch.setattr(worker_tasks, "_roll_failure", lambda rate: True)

    booking_id = make_booking()
    from app.config import get_settings

    max_retries = get_settings().worker_max_retries
    result = worker_tasks.confirm_booking.apply(
        args=[str(booking_id)], retries=max_retries
    ).get()

    assert result == "failed"
    assert _get_status(sync_engine, booking_id) == BookingStatus.failed


def test_worker_retries_on_failure_with_backoff(
    sync_engine, make_booking, monkeypatch
) -> None:
    from celery.exceptions import Retry

    monkeypatch.setattr(worker_tasks, "_roll_failure", lambda rate: True)

    booking_id = make_booking()
    with pytest.raises(Retry):
        worker_tasks.confirm_booking.apply(args=[str(booking_id)], throw=True).get()

    assert _get_status(sync_engine, booking_id) == BookingStatus.pending


def test_worker_idempotent_on_already_confirmed(
    sync_engine, make_booking, monkeypatch
) -> None:
    monkeypatch.setattr(worker_tasks, "_roll_failure", lambda rate: False)
    monkeypatch.setattr(worker_tasks, "send_notification", lambda *a, **kw: None)

    booking_id = make_booking()
    first = worker_tasks.confirm_booking.apply(args=[str(booking_id)]).get()
    assert first == "confirmed"

    monkeypatch.setattr(worker_tasks, "_roll_failure", lambda rate: True)
    second = worker_tasks.confirm_booking.apply(args=[str(booking_id)]).get()

    assert second == "confirmed"
    assert _get_status(sync_engine, booking_id) == BookingStatus.confirmed


def test_worker_skips_missing_booking() -> None:
    result = worker_tasks.confirm_booking.apply(args=[str(uuid.uuid4())]).get()
    assert result == "missing"
