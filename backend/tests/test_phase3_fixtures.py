from __future__ import annotations

import json
from pathlib import Path

from backend.scamflow.detection import (
    CaseSnapshot,
    DevelopmentMockExtractor,
    SnapshotEvent,
    decide_digital_arrest,
    validate_extraction,
)

FIXTURE_PATH = Path(__file__).parent / "fixtures" / "digital_arrest_phase3.json"


def load_fixture_set() -> dict[str, object]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def build_snapshot(
    family: dict[str, object],
    *,
    through_source_order: int | None = None,
) -> CaseSnapshot:
    events = family["events"]
    assert isinstance(events, list)

    selected_events = [
        event
        for event in events
        if through_source_order is None or event["source_order"] <= through_source_order
    ]

    payment_context = family["payment_context"]
    assert isinstance(payment_context, dict)

    return CaseSnapshot(
        case_id=str(family["family_id"]),
        revision=1,
        events=tuple(
            SnapshotEvent(
                event_id=str(event["event_id"]),
                channel=str(event["channel"]),
                text=str(event["text"]),
                source_order=int(event["source_order"]),
            )
            for event in selected_events
        ),
        stated_purpose=str(payment_context["stated_purpose"]),
        amount_decimal=(
            str(payment_context["amount"]) if payment_context["amount"] is not None else None
        ),
        recipient_reference=(
            str(payment_context["recipient_reference"])
            if payment_context["recipient_reference"] is not None
            else None
        ),
    )


def run_mock(snapshot: CaseSnapshot):
    extractor = DevelopmentMockExtractor()
    validated = validate_extraction(
        snapshot=snapshot,
        raw_output=extractor.extract(snapshot),
        extraction_mode=extractor.mode,
        extraction_version=extractor.version,
    )
    return validated, decide_digital_arrest(validated)


def test_fixture_expected_observations_match_exact_mock_output() -> None:
    fixture_set = load_fixture_set()
    families = fixture_set["families"]
    assert isinstance(families, list)

    checked = 0
    for family in families:
        assert isinstance(family, dict)
        expected = family.get("expected_observations")
        if expected is None:
            continue

        validated, _decision = run_mock(build_snapshot(family))

        actual = [
            {
                "tactic": item.tactic.value,
                "event_id": item.event_id,
                "quote": item.quote,
                "start": item.start,
                "end": item.end,
                "context": item.context.value,
            }
            for item in validated.observations
        ]

        assert actual == expected
        checked += 1

    assert checked >= 3


def test_fixture_prefix_policy_states_match_expected_labels() -> None:
    fixture_set = load_fixture_set()
    families = fixture_set["families"]
    assert isinstance(families, list)

    checked = 0
    for family in families:
        assert isinstance(family, dict)

        prefix_states = family["expected_prefix_states"]
        assert isinstance(prefix_states, list)

        for expected in prefix_states:
            through_source_order = int(expected["through_source_order"])
            snapshot = build_snapshot(
                family,
                through_source_order=through_source_order,
            )

            _validated, decision = run_mock(snapshot)

            assert decision.state == expected["state"]
            checked += 1

    assert checked >= 8


def test_fixture_metadata_explicitly_marks_development_only_provenance() -> None:
    fixture_set = load_fixture_set()

    assert fixture_set["fixture_set"] == ("phase3-digital-arrest-development-v1")
    assert "not a frozen held-out evaluation set" in str(fixture_set["purpose"]).lower()
    assert "synthetic" in str(fixture_set["provenance"]).lower()
    assert "phase 7/8" in str(fixture_set["evaluation_reservation"]).lower()
