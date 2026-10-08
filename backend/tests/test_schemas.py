from decimal import Decimal

import pytest
from pydantic import ValidationError

from backend.scamflow.schemas import (
    MAX_EVENTS,
    MAX_TOTAL_INPUT_CHARACTERS,
    AssessmentInput,
    AssessmentState,
    Channel,
)


def make_event(
    *,
    event_id: str = "evt-1",
    channel: str = "sms",
    text: str = "Please pay now.",
    source_order: object = 1,
) -> dict[str, object]:
    return {
        "event_id": event_id,
        "channel": channel,
        "text": text,
        "source_order": source_order,
    }


def make_input(
    *,
    events: list[dict[str, object]] | None = None,
    stated_purpose: str = "Refund verification",
    amount: object = None,
    recipient_reference: object = None,
) -> dict[str, object]:
    payment_context: dict[str, object] = {"stated_purpose": stated_purpose}
    if amount is not None:
        payment_context["amount"] = amount
    if recipient_reference is not None:
        payment_context["recipient_reference"] = recipient_reference

    return {
        "events": events if events is not None else [make_event()],
        "payment_context": payment_context,
    }


def test_minimal_valid_input() -> None:
    model = AssessmentInput.model_validate(make_input())

    assert model.events[0].event_id == "evt-1"
    assert model.events[0].channel is Channel.SMS
    assert model.events[0].source_order == 1
    assert model.payment_context.stated_purpose == "Refund verification"


def test_multiple_events_and_optional_payment_fields() -> None:
    model = AssessmentInput.model_validate(
        make_input(
            events=[
                make_event(event_id="evt-1", source_order=2),
                make_event(
                    event_id="evt-2",
                    channel="call_transcript",
                    text="Caller asked for an urgent transfer.",
                    source_order=1,
                ),
            ],
            amount="1500.50",
            recipient_reference="merchant-42",
        )
    )

    assert [event.source_order for event in model.events] == [2, 1]
    assert model.payment_context.amount == Decimal("1500.50")
    assert model.payment_context.recipient_reference == "merchant-42"


def test_original_event_text_is_preserved_exactly() -> None:
    original = "  First line\nSecond line\t  "
    model = AssessmentInput.model_validate(make_input(events=[make_event(text=original)]))

    assert model.events[0].text == original


def test_blank_optional_recipient_reference_becomes_none() -> None:
    model = AssessmentInput.model_validate(make_input(recipient_reference="  \t\n "))

    assert model.payment_context.recipient_reference is None


@pytest.mark.parametrize(
    ("payload", "missing_field"),
    [
        ({"payment_context": {"stated_purpose": "Refund"}}, "events"),
        ({"events": [make_event()]}, "payment_context"),
        (
            {
                "events": [
                    {
                        "channel": "sms",
                        "text": "Message",
                        "source_order": 1,
                    }
                ],
                "payment_context": {"stated_purpose": "Refund"},
            },
            "event_id",
        ),
    ],
)
def test_missing_required_fields_are_rejected(
    payload: dict[str, object],
    missing_field: str,
) -> None:
    with pytest.raises(ValidationError) as exc_info:
        AssessmentInput.model_validate(payload)

    assert missing_field in str(exc_info.value)


def test_unsupported_channel_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate(make_input(events=[make_event(channel="telegram")]))


@pytest.mark.parametrize(
    "payload",
    [
        make_input(events=[make_event(event_id="")]),
        make_input(events=[make_event(event_id="   ")]),
        make_input(events=[make_event(text="")]),
        make_input(events=[make_event(text=" \n\t ")]),
        make_input(stated_purpose=""),
        make_input(stated_purpose="   \n"),
    ],
)
def test_empty_or_whitespace_only_required_text_is_rejected(
    payload: dict[str, object],
) -> None:
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate(payload)


def test_duplicate_event_ids_are_rejected() -> None:
    with pytest.raises(ValidationError, match="event_id values must be unique"):
        AssessmentInput.model_validate(
            make_input(
                events=[
                    make_event(event_id="same", source_order=1),
                    make_event(event_id="same", source_order=2),
                ]
            )
        )


def test_duplicate_source_orders_are_rejected() -> None:
    with pytest.raises(
        ValidationError,
        match="source_order values must be unique",
    ):
        AssessmentInput.model_validate(
            make_input(
                events=[
                    make_event(event_id="evt-1", source_order=1),
                    make_event(event_id="evt-2", source_order=1),
                ]
            )
        )


@pytest.mark.parametrize(
    "source_order",
    [True, False, 0, -1, 1.0, "1", None],
)
def test_invalid_source_order_values_and_types_are_rejected(
    source_order: object,
) -> None:
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate(make_input(events=[make_event(source_order=source_order)]))


def test_empty_event_list_is_rejected() -> None:
    with pytest.raises(ValidationError):
        AssessmentInput.model_validate(make_input(events=[]))


@pytest.mark.parametrize(
    "amount",
    [
        0,
        -1,
        Decimal("Infinity"),
        Decimal("-Infinity"),
        Decimal("NaN"),
        True,
        False,
        "not-a-number",
        [],
        {},
    ],
)
def test_invalid_supplied_amounts_are_rejected(amount: object) -> None:
    payload = make_input()
    payload["payment_context"]["amount"] = amount  # type: ignore[index]

    with pytest.raises(ValidationError):
        AssessmentInput.model_validate(payload)


def test_exactly_twenty_events_are_accepted() -> None:
    events = [
        make_event(event_id=f"evt-{index}", text="x", source_order=index)
        for index in range(1, MAX_EVENTS + 1)
    ]

    model = AssessmentInput.model_validate(make_input(events=events, stated_purpose="p"))

    assert len(model.events) == MAX_EVENTS


def test_twenty_one_events_are_rejected() -> None:
    events = [
        make_event(event_id=f"evt-{index}", text="x", source_order=index)
        for index in range(1, MAX_EVENTS + 2)
    ]

    with pytest.raises(ValidationError):
        AssessmentInput.model_validate(make_input(events=events, stated_purpose="p"))


def test_exactly_twelve_thousand_counted_characters_are_accepted() -> None:
    event_text = "x" * (MAX_TOTAL_INPUT_CHARACTERS - 1)

    model = AssessmentInput.model_validate(
        make_input(events=[make_event(text=event_text)], stated_purpose="p")
    )

    assert len(model.events[0].text) + len(model.payment_context.stated_purpose) == (
        MAX_TOTAL_INPUT_CHARACTERS
    )


def test_twelve_thousand_and_one_counted_characters_are_rejected() -> None:
    event_text = "x" * MAX_TOTAL_INPUT_CHARACTERS

    with pytest.raises(ValidationError, match="must not exceed 12000 characters"):
        AssessmentInput.model_validate(
            make_input(events=[make_event(text=event_text)], stated_purpose="p")
        )


def test_combined_fields_share_the_same_character_limit() -> None:
    event_text = "x" * 11_990

    with pytest.raises(ValidationError, match="must not exceed 12000 characters"):
        AssessmentInput.model_validate(
            make_input(
                events=[make_event(text=event_text)],
                stated_purpose="purpose",
                recipient_reference="recipient",
            )
        )


def test_unicode_limit_uses_python_string_length_not_utf8_bytes() -> None:
    event_text = "🙂" * (MAX_TOTAL_INPUT_CHARACTERS - 1)

    model = AssessmentInput.model_validate(
        make_input(events=[make_event(text=event_text)], stated_purpose="p")
    )

    assert len(model.events[0].text) == MAX_TOTAL_INPUT_CHARACTERS - 1
    assert len(model.events[0].text.encode("utf-8")) > len(model.events[0].text)


def test_assessment_state_values_are_stable() -> None:
    assert [state.value for state in AssessmentState] == [
        "high_risk_indicators",
        "needs_clarification_or_review",
        "no_strong_indicators",
        "unable_to_assess",
    ]
