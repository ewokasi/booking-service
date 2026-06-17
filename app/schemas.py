import uuid
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator

from app.models import BookingStatus


class BookingCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    datetime: datetime
    service_type: str = Field(..., min_length=1, max_length=64)

    @field_validator("datetime")
    @classmethod
    def _datetime_must_be_future(cls, value: datetime) -> datetime:
        moment = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
        if moment <= datetime.now(UTC):
            raise ValueError("datetime must be in the future")
        return moment


class BookingRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    name: str
    datetime: datetime
    service_type: str
    status: BookingStatus
    created_at: datetime
    updated_at: datetime


class BookingList(BaseModel):
    items: list[BookingRead]
    total: int
    limit: int
    offset: int
