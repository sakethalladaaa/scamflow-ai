"""Pydantic contracts used by the ScamFlow AI backend."""

from decimal import Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StrictInt,
    field_validator,
    model_validator,
)

MAX_EVENTS = 20
MAX_TOTAL_INPUT_CHARACTERS = 12_000
MAX_EVENT_ID_CHARACTERS = 128
MAX_RECIPIENT_REFERENCE_CHARACTERS = 256
MAX_SOURCE_ORDER = 1_000_000


class Channel(StrEnum):
    """Supported channels for manually submitted text evidence."""

    SMS = "sms"
    WHATSAPP = "whatsapp"
    CALL_TRANSCRIPT = "call_transcript"
    EMAIL = "email"
    OTHER_TEXT = "other_text"


class AssessmentState(StrEnum):
    """High-level assessment states reserved for later detector phases.

    NO_STRONG_INDICATORS is not a guarantee that an interaction is safe.
    UNABLE_TO_ASSESS means the assessment was incomplete or failed; it does
    not represent low risk.
    """

    HIGH_RISK_INDICATORS = "high_risk_indicators"
    NEEDS_CLARIFICATION_OR_REVIEW = "needs_clarification_or_review"
    NO_STRONG_INDICATORS = "no_strong_indicators"
    UNABLE_TO_ASSESS = "unable_to_assess"


class HealthResponse(BaseModel):
    """Stable liveness response."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    status: Literal["ok"] = "ok"


class ScamEvent(BaseModel):
    """One user-submitted message or transcript event.

    ``source_order`` is a positive, 1-based source sequence number supplied
    by the caller. Values must be unique within a request. Events are not
    silently reordered: list position and ``source_order`` remain distinct.
    """

    model_config = ConfigDict(extra="forbid")

    event_id: str = Field(max_length=MAX_EVENT_ID_CHARACTERS)
    channel: Channel
    text: str = Field(max_length=MAX_TOTAL_INPUT_CHARACTERS)
    source_order: Annotated[StrictInt, Field(ge=1, le=MAX_SOURCE_ORDER)]

    @field_validator("event_id")
    @classmethod
    def validate_event_id(cls, value: str) -> str:
        normalized = value.strip()
        if not normalized:
            raise ValueError("event_id must not be empty or whitespace-only")
        return normalized

    @field_validator("text")
    @classmethod
    def validate_text(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("text must not be empty or whitespace-only")
        # Preserve the original text exactly because future evidence offsets
        # depend on its original character positions.
        return value


class PaymentContext(BaseModel):
    """User-stated payment context associated with submitted events."""

    model_config = ConfigDict(extra="forbid")

    stated_purpose: str = Field(max_length=MAX_TOTAL_INPUT_CHARACTERS)
    amount: Decimal | None = None
    recipient_reference: str | None = Field(
        default=None,
        max_length=MAX_RECIPIENT_REFERENCE_CHARACTERS,
    )

    @field_validator("stated_purpose")
    @classmethod
    def validate_stated_purpose(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("stated_purpose must not be empty or whitespace-only")
        return value

    @field_validator("recipient_reference", mode="before")
    @classmethod
    def normalize_blank_recipient_reference(cls, value: object) -> object:
        if value is None:
            return None
        if isinstance(value, str) and not value.strip():
            return None
        return value

    @field_validator("amount", mode="before")
    @classmethod
    def reject_boolean_amount(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("amount must be a positive finite decimal value")
        return value

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value: Decimal | None) -> Decimal | None:
        if value is None:
            return None
        if not value.is_finite() or value <= 0:
            raise ValueError("amount must be a positive finite decimal value")
        return value


class AssessmentInput(BaseModel):
    """Validated input contract for future scam assessment phases.

    The combined character limit uses Python ``len(str)`` semantics: Unicode
    code points in event text, stated purpose, and recipient reference are
    counted as Python string characters, not bytes or model tokens.
    """

    model_config = ConfigDict(extra="forbid")

    events: list[ScamEvent] = Field(min_length=1, max_length=MAX_EVENTS)
    payment_context: PaymentContext

    @model_validator(mode="after")
    def validate_request(self) -> "AssessmentInput":
        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event_id values must be unique")

        source_orders = [event.source_order for event in self.events]
        if len(set(source_orders)) != len(source_orders):
            raise ValueError("source_order values must be unique")

        recipient_reference = self.payment_context.recipient_reference or ""
        total_characters = (
            sum(len(event.text) for event in self.events)
            + len(self.payment_context.stated_purpose)
            + len(recipient_reference)
        )
        if total_characters > MAX_TOTAL_INPUT_CHARACTERS:
            raise ValueError(
                "combined event text, stated purpose, and recipient reference "
                f"must not exceed {MAX_TOTAL_INPUT_CHARACTERS} characters"
            )

        return self
