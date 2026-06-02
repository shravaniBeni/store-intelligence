from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class EventType(str, Enum):
    ENTRY = "ENTRY"
    EXIT = "EXIT"
    ZONE_ENTER = "ZONE_ENTER"
    ZONE_EXIT = "ZONE_EXIT"
    ZONE_DWELL = "ZONE_DWELL"
    BILLING_QUEUE_JOIN = "BILLING_QUEUE_JOIN"
    BILLING_QUEUE_ABANDON = "BILLING_QUEUE_ABANDON"
    REENTRY = "REENTRY"


class EventMetadata(BaseModel):
    queue_depth: int | None = None
    sku_zone: str | None = None
    session_seq: int = 1
    source_track_id: str | None = None
    reid_reason: str | None = None
    staff_reason: str | None = None


class StoreEvent(BaseModel):
    event_id: UUID
    store_id: str = Field(min_length=1)
    camera_id: str = Field(min_length=1)
    visitor_id: str = Field(min_length=1)
    event_type: EventType
    timestamp: datetime
    zone_id: str | None = None
    dwell_ms: int = Field(ge=0)
    is_staff: bool = False
    confidence: float = Field(ge=0.0, le=1.0)
    metadata: EventMetadata = Field(default_factory=EventMetadata)

    @field_validator("timestamp")
    @classmethod
    def require_timezone(cls, value: datetime) -> datetime:
        if value.tzinfo is None:
            raise ValueError("timestamp must include timezone")
        return value


class IngestRequest(BaseModel):
    events: list[StoreEvent] = Field(max_length=500)


class IngestFailure(BaseModel):
    index: int
    error: str


class IngestResponse(BaseModel):
    accepted: int
    duplicates: int
    failed: list[IngestFailure]


class Transaction(BaseModel):
    store_id: str
    transaction_id: str
    timestamp: datetime
    basket_value_inr: float = Field(ge=0)

