"""Phase 2 API request and response contracts."""

from datetime import datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StrictInt, model_validator

from .schemas import MAX_EVENTS, AssessmentInput, AssessmentState, PaymentContext, ScamEvent


class SessionResponse(BaseModel):
    """Public session metadata; never includes the opaque session token."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expires_at: datetime


class CreateCaseRequest(BaseModel):
    """A consented case creation request."""

    model_config = ConfigDict(extra="forbid")

    consent: Literal[True]
    payment_context: PaymentContext
    events: list[ScamEvent] = Field(min_length=1, max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def reuse_phase1_input_validation(self) -> "CreateCaseRequest":
        AssessmentInput(
            events=self.events,
            payment_context=self.payment_context,
        )
        return self


class AppendEventsRequest(BaseModel):
    """Append evidence against one explicitly expected case revision."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[StrictInt, Field(ge=1)]
    events: list[ScamEvent] = Field(min_length=1, max_length=MAX_EVENTS)

    @model_validator(mode="after")
    def validate_request_local_uniqueness(self) -> "AppendEventsRequest":
        event_ids = [event.event_id for event in self.events]
        if len(set(event_ids)) != len(event_ids):
            raise ValueError("event_id values must be unique")

        source_orders = [event.source_order for event in self.events]
        if len(set(source_orders)) != len(source_orders):
            raise ValueError("source_order values must be unique")

        return self


class StoredEventResponse(BaseModel):
    """One persisted evidence event."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    event_id: str
    channel: str
    text: str
    source_order: int
    ingested_at: datetime


class CaseResponse(BaseModel):
    """Current persisted case state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    consent_version: str
    consented_at: datetime
    payment_context: PaymentContext
    revision: int
    created_at: datetime
    updated_at: datetime
    expires_at: datetime
    events: list[StoredEventResponse]


class MutationResponse(BaseModel):
    """Stable logical result of an idempotent create or append."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    case_id: str
    result_revision: int
    idempotent_replay: bool


class ErrorDetail(BaseModel):
    """Safe error detail without request bodies, secrets, or database text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str
    message: str


class ErrorResponse(BaseModel):
    """Consistent public API error envelope."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    detail: ErrorDetail


class AssessCaseRequest(BaseModel):
    """Request an assessment of one exact persisted case revision."""

    model_config = ConfigDict(extra="forbid")

    expected_revision: Annotated[StrictInt, Field(ge=1)]


class AssessmentEvidenceResponse(BaseModel):
    """One exact validated evidence span used by an assessment."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    tactic: str
    event_id: str
    source_order: int
    quote: str
    start_offset: int
    end_offset: int
    context: str


class AlertResponse(BaseModel):
    """Controlled presentation decision backed by persisted alert memory."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    visible: bool
    reason: str
    prior_warning_state: AssessmentState | None = None


class AssessmentResponse(BaseModel):
    """Persisted assessment result for one fixed case revision."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    assessment_id: str
    case_id: str
    assessed_revision: int
    state: AssessmentState
    reason_codes: list[str]
    explanation: str
    evidence: list[AssessmentEvidenceResponse]
    alert: AlertResponse
    tactics_used: list[str]
    relationships: list[str]
    suggested_next_action: str
    limitations: list[str]

    extraction_mode: str
    extraction_version: str
    rule_version: str
    schema_version: str

    created_at: datetime
    is_current: bool
    idempotent_replay: bool
