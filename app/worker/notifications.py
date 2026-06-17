from app.logging import get_logger

log = get_logger(__name__)


def send_notification(booking_id: str, name: str, service_type: str) -> None:
    log.info(
        "notification_sent",
        booking_id=booking_id,
        name=name,
        service_type=service_type,
        channel="mock",
    )
