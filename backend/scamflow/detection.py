"""Phase 3 extraction, evidence validation, and Digital Arrest policy rules.

The development mock is deliberately narrow and deterministic. It is not a
real scam detector and must never be presented as production inference.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import StrEnum
from typing import Any, Protocol

from pydantic import BaseModel, ConfigDict, Field, StrictInt, StrictStr, ValidationError

EXTRACTION_SCHEMA_VERSION = "phase3-extraction-v1"
# Kept stable for backward-compatible responses; Fake Refund is an additive
# policy family and is identified by its reason codes and extractor v2.
DIGITAL_ARREST_RULE_VERSION = "digital-arrest-v1"
MOCK_EXTRACTION_MODE = "development_mock"
MOCK_EXTRACTION_VERSION = "digital-arrest-and-refund-patterns-v2"

MAX_EXTRACTED_OBSERVATIONS = 40
MAX_EVIDENCE_QUOTE_CHARACTERS = 2_000


class ObservationType(StrEnum):
    """Supported evidence-linked observations for Digital Arrest detection."""

    AUTHORITY_CLAIM = "authority_claim"
    INVESTIGATION_ALLEGATION = "investigation_allegation"
    THREAT_COERCION = "threat_coercion"
    SECRECY = "secrecy"
    ISOLATION = "isolation"
    VERIFICATION_TRANSFER_REQUEST = "verification_transfer_request"
    CLAIMED_REFUND = "claimed_refund"
    ADVANCE_PAYMENT_REQUEST = "advance_payment_request"
    SENSITIVE_CREDENTIAL_REQUEST = "sensitive_credential_request"
    REMOTE_ACCESS_REQUEST = "remote_access_request"
    EXCESS_REFUND_REPAYMENT = "excess_refund_repayment"
    RECIPIENT_MISMATCH = "recipient_mismatch"


class EvidenceContext(StrEnum):
    """How the referenced text is being used in the source event."""

    ASSERTED = "asserted"
    NEGATED = "negated"
    QUOTED_WARNING = "quoted_warning"


@dataclass(frozen=True)
class SnapshotEvent:
    """Immutable event copied from one persisted case revision."""

    event_id: str
    channel: str
    text: str
    source_order: int


@dataclass(frozen=True)
class CaseSnapshot:
    """Immutable persisted evidence supplied to an extractor."""

    case_id: str
    revision: int
    events: tuple[SnapshotEvent, ...]
    stated_purpose: str
    amount_decimal: str | None
    recipient_reference: str | None


@dataclass(frozen=True)
class ValidatedObservation:
    """Extractor evidence that has passed exact source-span validation."""

    tactic: ObservationType
    event_id: str
    quote: str
    start: int
    end: int
    context: EvidenceContext


@dataclass(frozen=True)
class ValidatedExtraction:
    """Validated structured observations or an explicit unsupported result."""

    supported: bool
    observations: tuple[ValidatedObservation, ...]
    extraction_mode: str
    extraction_version: str


@dataclass(frozen=True)
class PolicyDecision:
    """Deterministic Digital Arrest policy result."""

    state: str
    reason_codes: tuple[str, ...]
    explanation: str
    used_tactics: tuple[str, ...]
    relationships: tuple[str, ...]
    suggested_next_action: str
    limitations: tuple[str, ...]


class ExtractionValidationError(Exception):
    """Safe marker for malformed or untraceable extractor output."""


class Extractor(Protocol):
    """Injectable structured-observation extractor."""

    mode: str
    version: str

    def extract(self, snapshot: CaseSnapshot) -> object:
        """Return untrusted structured output for later validation."""


class _ObservationPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tactic: ObservationType
    event_id: StrictStr
    quote: StrictStr = Field(min_length=1, max_length=MAX_EVIDENCE_QUOTE_CHARACTERS)
    start: StrictInt
    end: StrictInt
    context: EvidenceContext


class _ExtractionPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    status: StrictStr
    observations: list[_ObservationPayload] = Field(max_length=MAX_EXTRACTED_OBSERVATIONS)


def _context_for_match(text: str, start: int) -> EvidenceContext:
    """Classify only a few explicit development-fixture contexts.

    This intentionally does not attempt general natural-language understanding.
    """

    lowered = text.lower()
    prefix = lowered[max(0, start - 80) : start]

    warning_markers = (
        "scam warning",
        "fraud warning",
        "example:",
        "example ",
        "they may say",
        "a scammer may say",
        "never ask",
        "will never ask",
    )
    if any(marker in lowered for marker in warning_markers):
        return EvidenceContext.QUOTED_WARNING

    if re.search(
        r"\b(?:not|no)\s+(?:(?:a|an|the)\s+)?$",
        prefix,
    ):
        return EvidenceContext.NEGATED

    return EvidenceContext.ASSERTED


def _find_literal_observations(
    *,
    event: SnapshotEvent,
    tactic: ObservationType,
    phrases: tuple[str, ...],
) -> list[dict[str, Any]]:
    """Return exact spans for configured literal development patterns."""

    lowered = event.text.lower()
    observations: list[dict[str, Any]] = []

    for phrase in phrases:
        search_from = 0
        while True:
            start = lowered.find(phrase, search_from)
            if start < 0:
                break
            end = start + len(phrase)
            observations.append(
                {
                    "tactic": tactic.value,
                    "event_id": event.event_id,
                    "quote": event.text[start:end],
                    "start": start,
                    "end": end,
                    "context": _context_for_match(event.text, start).value,
                }
            )
            search_from = end

    return observations


class DevelopmentMockExtractor:
    """Small content-driven mock used only for development and tests.

    It recognizes a disclosed fixed vocabulary. Unknown content is explicitly
    unsupported rather than being interpreted as reassuring empty evidence.
    """

    mode = MOCK_EXTRACTION_MODE
    version = MOCK_EXTRACTION_VERSION

    _PATTERNS: tuple[tuple[ObservationType, tuple[str, ...]], ...] = (
        (
            ObservationType.AUTHORITY_CLAIM,
            (
                "police officer",
                "cyber crime officer",
                "cbi officer",
                "rbi officer",
                "government officer",
            ),
        ),
        (
            ObservationType.INVESTIGATION_ALLEGATION,
            (
                "under investigation",
                "money laundering case",
                "case has been filed",
                "criminal investigation",
            ),
        ),
        (
            ObservationType.THREAT_COERCION,
            (
                "you will be arrested",
                "arrest warrant",
                "freeze your account",
                "legal action against you",
            ),
        ),
        (
            ObservationType.SECRECY,
            (
                "do not tell anyone",
                "don't tell anyone",
                "keep this secret",
            ),
        ),
        (
            ObservationType.ISOLATION,
            (
                "stay on the call",
                "do not disconnect",
                "don't disconnect",
            ),
        ),
        (
            ObservationType.VERIFICATION_TRANSFER_REQUEST,
            (
                "transfer money for verification",
                "transfer the money for verification",
                "send money for verification",
                "pay money for verification",
                "transfer funds for verification",
                "transfer money to resolve the case",
                "pay to resolve the case",
            ),
        ),
        (
            ObservationType.CLAIMED_REFUND,
            (
                "refund has been approved",
                "refund is ready",
                "refund is pending",
                "process your refund",
                "receive your refund",
            ),
        ),
        (
            ObservationType.ADVANCE_PAYMENT_REQUEST,
            (
                "pay a processing fee",
                "pay the processing fee",
                "pay a refundable fee",
                "send money before the refund",
                "pay first to receive",
            ),
        ),
        (
            ObservationType.SENSITIVE_CREDENTIAL_REQUEST,
            (
                "share your otp",
                "send your otp",
                "share your pin",
                "send your cvv",
                "share your password",
            ),
        ),
        (
            ObservationType.REMOTE_ACCESS_REQUEST,
            (
                "install anydesk",
                "install teamviewer",
                "install the remote access app",
                "allow screen sharing",
            ),
        ),
        (
            ObservationType.EXCESS_REFUND_REPAYMENT,
            (
                "refunded too much",
                "accidental excess refund",
                "refund was too high",
                "repay the extra refund",
                "return the excess refund",
            ),
        ),
        (
            ObservationType.RECIPIENT_MISMATCH,
            (
                "send it to a different account",
                "pay a personal account",
                "transfer to another recipient",
                "send it to this other upi",
            ),
        ),
    )

    # These phrases let synthetic benign fixtures exercise a successfully
    # processed empty observation set without treating arbitrary unknown text
    # as evidence-free.
    _SUPPORTED_BENIGN_MARKERS = (
        "appointment confirmed",
        "reference number",
        "visit the branch",
        "official helpline",
        "document submission",
        "service request",
        "please respond by",
        "urgent appointment",
        "refund will return to the original payment method",
        "no fee is required for this refund",
        "refund status is available in your order history",
    )

    def extract(self, snapshot: CaseSnapshot) -> object:
        observations: list[dict[str, Any]] = []
        vocabulary_seen = False

        for event in snapshot.events:
            lowered = event.text.lower()

            if any(marker in lowered for marker in self._SUPPORTED_BENIGN_MARKERS):
                vocabulary_seen = True

            for tactic, phrases in self._PATTERNS:
                matched = _find_literal_observations(
                    event=event,
                    tactic=tactic,
                    phrases=phrases,
                )
                if matched:
                    vocabulary_seen = True
                    observations.extend(matched)

        if not vocabulary_seen:
            return {"status": "unsupported", "observations": []}

        return {"status": "ok", "observations": observations}


def validate_extraction(
    *,
    snapshot: CaseSnapshot,
    raw_output: object,
    extraction_mode: str,
    extraction_version: str,
) -> ValidatedExtraction:
    """Strictly validate untrusted extractor output against the snapshot."""

    try:
        payload = _ExtractionPayload.model_validate(raw_output)
    except ValidationError as exc:
        raise ExtractionValidationError("malformed_extraction") from exc

    if payload.status not in {"ok", "unsupported"}:
        raise ExtractionValidationError("malformed_extraction")

    if payload.status == "unsupported":
        if payload.observations:
            raise ExtractionValidationError("malformed_extraction")
        return ValidatedExtraction(
            supported=False,
            observations=(),
            extraction_mode=extraction_mode,
            extraction_version=extraction_version,
        )

    events = {event.event_id: event for event in snapshot.events}
    validated: list[ValidatedObservation] = []
    seen: set[tuple[str, str, int, int, str]] = set()

    for observation in payload.observations:
        event = events.get(observation.event_id)
        if event is None:
            raise ExtractionValidationError("invalid_evidence_reference")

        start = observation.start
        end = observation.end
        if start < 0 or end <= start or end > len(event.text):
            raise ExtractionValidationError("invalid_evidence_span")

        exact_quote = event.text[start:end]
        if observation.quote != exact_quote:
            raise ExtractionValidationError("evidence_quote_mismatch")

        key = (
            observation.tactic.value,
            observation.event_id,
            start,
            end,
            observation.context.value,
        )
        if key in seen:
            continue
        seen.add(key)

        validated.append(
            ValidatedObservation(
                tactic=observation.tactic,
                event_id=observation.event_id,
                quote=observation.quote,
                start=start,
                end=end,
                context=observation.context,
            )
        )

    return ValidatedExtraction(
        supported=True,
        observations=tuple(validated),
        extraction_mode=extraction_mode,
        extraction_version=extraction_version,
    )


def decide_digital_arrest(
    extraction: ValidatedExtraction,
) -> PolicyDecision:
    """Apply transparent Digital Arrest rules, version DIGITAL_ARREST_RULE_VERSION."""

    common_limitations = (
        "This assessment uses a narrow development mock extractor, not production AI.",
        "Evidence spans prove traceability to submitted text, not semantic correctness.",
        "No result authenticates a sender or guarantees that an interaction is safe.",
    )

    if not extraction.supported:
        return PolicyDecision(
            state="unable_to_assess",
            reason_codes=("mock_input_unsupported",),
            explanation=(
                "The development mock does not support this input vocabulary, so no "
                "risk conclusion was produced."
            ),
            used_tactics=(),
            relationships=(),
            suggested_next_action=(
                "Do not treat this as a low-risk result; review the interaction manually "
                "or retry later with a supported extractor."
            ),
            limitations=common_limitations,
        )

    active = tuple(
        observation
        for observation in extraction.observations
        if observation.context is EvidenceContext.ASSERTED
    )
    active_types = {observation.tactic for observation in active}

    authority = ObservationType.AUTHORITY_CLAIM in active_types
    coercion = ObservationType.THREAT_COERCION in active_types
    secrecy = ObservationType.SECRECY in active_types
    isolation = ObservationType.ISOLATION in active_types
    transfer = ObservationType.VERIFICATION_TRANSFER_REQUEST in active_types
    investigation = ObservationType.INVESTIGATION_ALLEGATION in active_types
    claimed_refund = ObservationType.CLAIMED_REFUND in active_types

    refund_risk_tactics = (
        ObservationType.ADVANCE_PAYMENT_REQUEST,
        ObservationType.SENSITIVE_CREDENTIAL_REQUEST,
        ObservationType.REMOTE_ACCESS_REQUEST,
        ObservationType.EXCESS_REFUND_REPAYMENT,
        ObservationType.RECIPIENT_MISMATCH,
    )

    if claimed_refund and active_types.intersection(refund_risk_tactics):
        used = [ObservationType.CLAIMED_REFUND.value]
        used.extend(
            tactic.value
            for tactic in refund_risk_tactics
            if tactic in active_types
        )
        return PolicyDecision(
            state="high_risk_indicators",
            reason_codes=("refund_linked_to_payment_credentials_or_mismatch",),
            explanation=(
                "The submitted evidence links a claimed refund to an advance payment, "
                "sensitive credential or remote-access request, excess-refund repayment, "
                "or a different recipient."
            ),
            used_tactics=tuple(used),
            relationships=("claimed_refund_linked_to_suspicious_follow_up",),
            suggested_next_action=(
                "Do not pay, share credentials, or install remote-access software; "
                "verify the refund in the merchant's official app or website."
            ),
            limitations=common_limitations,
        )

    if authority and coercion and (secrecy or isolation):
        used = [
            ObservationType.AUTHORITY_CLAIM.value,
            ObservationType.THREAT_COERCION.value,
        ]
        if secrecy:
            used.append(ObservationType.SECRECY.value)
        if isolation:
            used.append(ObservationType.ISOLATION.value)

        return PolicyDecision(
            state="high_risk_indicators",
            reason_codes=("authority_coercion_isolation_or_secrecy",),
            explanation=(
                "The submitted evidence combines an asserted official-authority claim "
                "with coercion and secrecy or isolation instructions."
            ),
            used_tactics=tuple(used),
            relationships=("contextual_combination_across_ordered_evidence",),
            suggested_next_action=(
                "Pause any payment or sensitive action and independently verify the "
                "request using an official channel you locate yourself."
            ),
            limitations=common_limitations,
        )

    if authority and coercion and transfer:
        return PolicyDecision(
            state="high_risk_indicators",
            reason_codes=("coercive_authority_verification_transfer",),
            explanation=(
                "The submitted evidence combines an asserted official-authority claim "
                "and coercion with a request to transfer money for verification or "
                "resolution."
            ),
            used_tactics=(
                ObservationType.AUTHORITY_CLAIM.value,
                ObservationType.THREAT_COERCION.value,
                ObservationType.VERIFICATION_TRANSFER_REQUEST.value,
            ),
            relationships=("coercive_authority_linked_to_transfer_demand",),
            suggested_next_action=(
                "Do not make the requested transfer based only on this interaction; "
                "independently verify the request using an official channel."
            ),
            limitations=common_limitations,
        )

    suspicious = {
        ObservationType.AUTHORITY_CLAIM,
        ObservationType.INVESTIGATION_ALLEGATION,
        ObservationType.THREAT_COERCION,
        ObservationType.SECRECY,
        ObservationType.ISOLATION,
        ObservationType.VERIFICATION_TRANSFER_REQUEST,
        ObservationType.CLAIMED_REFUND,
        *refund_risk_tactics,
    }
    suspicious_active = tuple(
        observation.tactic.value for observation in active if observation.tactic in suspicious
    )

    if (
        coercion
        or secrecy
        or isolation
        or transfer
        or (authority and investigation)
        or active_types.intersection(refund_risk_tactics)
    ):
        return PolicyDecision(
            state="needs_clarification_or_review",
            reason_codes=("incomplete_suspicious_context",),
            explanation=(
                "Some active suspicious context is present, but the evidence does not "
                "meet the Phase 3 high-risk rule combinations."
            ),
            used_tactics=tuple(dict.fromkeys(suspicious_active)),
            relationships=("missing_context_for_high_risk_rule",),
            suggested_next_action=(
                "Pause before acting and obtain independent context or manual review."
            ),
            limitations=common_limitations,
        )

    return PolicyDecision(
        state="no_strong_indicators",
        reason_codes=("no_phase3_high_risk_combination",),
        explanation=(
            "The supported development input did not contain the Phase 3 combinations "
            "required for a stronger Digital Arrest warning."
        ),
        used_tactics=tuple(dict.fromkeys(suspicious_active)),
        relationships=(),
        suggested_next_action=(
            "Continue cautiously; this result is not a guarantee that the interaction is safe."
        ),
        limitations=common_limitations,
    )
