import random
import uuid

from celery import Task

from app.config import get_settings
from app.logging import get_logger
from app.models import Booking, BookingStatus
from app.worker.celery_app import celery_app
from app.worker.db_sync import sync_session_scope
from app.worker.notifications import send_notification

log = get_logger(__name__)


class ExternalServiceError(RuntimeError):
    pass


def _roll_failure(rate: float) -> bool:
    return random.random() < rate


@celery_app.task(bind=True, name="bookings.confirm", max_retries=None)
def confirm_booking(self: Task, booking_id: str) -> str:
    settings = get_settings()
    self.max_retries = settings.worker_max_retries

    bid = uuid.UUID(booking_id)

    with sync_session_scope() as session:
        booking = session.get(Booking, bid, with_for_update=True)
        if booking is None:
            log.warning("confirm_skip_missing", booking_id=booking_id)
            return "missing"

        if booking.status != BookingStatus.pending:
            log.info(
                "confirm_skip_idempotent",
                booking_id=booking_id,
                status=booking.status.value,
            )
            return booking.status.value

        if not _roll_failure(settings.worker_failure_rate):
            booking.status = BookingStatus.confirmed
            session.commit()
            send_notification(booking_id, booking.name, booking.service_type)
            log.info("confirm_success", booking_id=booking_id)
            return BookingStatus.confirmed.value

        exc = ExternalServiceError("downstream confirm failed")

        if self.request.retries >= settings.worker_max_retries:
            booking.status = BookingStatus.failed
            session.commit()
            log.error(
                "confirm_failed_terminal",
                booking_id=booking_id,
                attempts=self.request.retries + 1,
            )
            return BookingStatus.failed.value

        session.rollback()
        countdown = settings.worker_retry_backoff ** self.request.retries
        log.warning(
            "confirm_retry",
            booking_id=booking_id,
            attempt=self.request.retries + 1,
            countdown=countdown,
            error=str(exc),
        )
        raise self.retry(exc=exc, countdown=countdown)
