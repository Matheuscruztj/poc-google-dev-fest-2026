"""Public data schemas and catalog validation."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Session(BaseModel):
    model_config = ConfigDict(extra="forbid")
    id: str
    title: str
    track: str
    level: Literal["iniciante", "intermediario", "avancado"]
    starts_at: datetime
    ends_at: datetime
    capacity: int = Field(gt=0)

    @model_validator(mode="after")
    def valid_interval(self) -> Session:
        if (
            self.ends_at.tzinfo is None
            or self.starts_at.tzinfo is None
            or self.ends_at <= self.starts_at
        ):
            raise ValueError("A sessão precisa ter horário explícito e duração positiva.")
        return self


class ScheduleRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    track: str | None = None
    level: str | None = None
    after: datetime | None = None
    limit: int = Field(default=3, ge=1, le=3)


class FAQRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    question: str = Field(min_length=2, max_length=1000)


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    message: str = Field(min_length=2, max_length=2000)
    architecture: Literal["single", "multi"] = "single"


class PreviewRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str


class ReservationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    session_id: str
    confirmation_token: str
    idempotency_key: str = Field(min_length=8, max_length=128)
