import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from app.models import BookingStatus


class BookingCreate(BaseModel):
    name: str = Field(..., min_length=1, max_length=255)
    datetime: datetime
    service_type: str = Field(..., min_length=1, max_length=64)


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
