from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.scamflow.app import create_app
from backend.scamflow.detection import DevelopmentMockExtractor
from backend.scamflow.models import (
    Assessment,
    AssessmentEvidence,
    AssessmentIdempotencyRecord,
)
from backend.scamflow.security import CSRF_HEADER_NAME
from backend.scamflow.settings import Environment, Settings

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"Origin": ORIGIN, CSRF_HEADER_NAME: "1"}


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_path": tmp_path / "assessments.sqlite3",
        "trusted_origin": ORIGIN,
    }
    values.update(overrides)
    return Settings(**values)


def bootstrap(client: TestClient) -> None:
    response = client.post("/session", headers=HEADERS)
    assert response.status_code == 200


def create_case(
    client: TestClient,
    *,
    key: str = "create-1",
    text: str = ("I am a police officer. You will be arrested. Stay on the call."),
    purpose: str = "Verification",
):
    return client.post(
        "/cases",
        headers={**HEADERS, "Idempotency-Key": key},
        json={
            "consent": True,
            "payment_context": {
                "stated_purpose": purpose,
                "amount": "5000",
                "recipient_reference": "recipient-1",
            },
            "events": [
                {
                    "event_id": "evt-1",
                    "channel": "call_transcript",
                    "text": text,
                    "source_order": 1,
                }
            ],
        },
    )


def assess(
    client: TestClient,
    case_id: str,
    *,
    key: str = "assess-1",
    expected_revision: int = 1,
):
    return client.post(
        f"/cases/{case_id}/assess",
        headers={**HEADERS, "Idempotency-Key": key},
        json={"expected_revision": expected_revision},
    )


def append_event(
    client: TestClient,
    case_id: str,
    *,
    key: str = "append-1",
    expected_revision: int = 1,
):
    return client.post(
        f"/cases/{case_id}/events",
        headers={**HEADERS, "Idempotency-Key": key},
        json={
            "expected_revision": expected_revision,
            "events": [
                {
                    "event_id": "evt-2",
                    "channel": "sms",
                    "text": "Reference number ABC-123.",
                    "source_order": 2,
                }
            ],
        },
    )


def test_assessment_is_persisted_and_retrievable(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        created = create_case(client)
        assert created.status_code == 201
        case_id = created.json()["case_id"]

        response = assess(client, case_id)

        assert response.status_code == 200
        body = response.json()
        assert body["case_id"] == case_id
        assert body["assessed_revision"] == 1
        assert body["state"] == "high_risk_indicators"
        assert body["reason_codes"] == ["authority_coercion_isolation_or_secrecy"]
        assert body["is_current"] is True
        assert body["idempotent_replay"] is False
        assert body["extraction_mode"] == "development_mock"
        assert body["rule_version"] == "digital-arrest-v1"
        assert body["schema_version"] == "phase3-extraction-v1"
        assert body["evidence"]
        assert all(item["quote"] for item in body["evidence"])

        latest = client.get(f"/cases/{case_id}/assessments/latest")
        assert latest.status_code == 200
        assert latest.json()["assessment_id"] == body["assessment_id"]
        assert latest.json()["is_current"] is True
        assert latest.json()["idempotent_replay"] is False

        with app.state.database.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Assessment)
                    .where(Assessment.case_id == case_id)
                )
                == 1
            )
            assert session.scalar(select(func.count()).select_from(AssessmentEvidence)) == len(
                body["evidence"]
            )


def test_latest_assessment_becomes_visibly_stale_after_append(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        first = assess(client, case_id)
        assert first.status_code == 200
        assert first.json()["is_current"] is True

        appended = append_event(client, case_id)
        assert appended.status_code == 200
        assert appended.json()["result_revision"] == 2

        latest = client.get(f"/cases/{case_id}/assessments/latest")
        assert latest.status_code == 200
        assert latest.json()["assessed_revision"] == 1
        assert latest.json()["is_current"] is False


def test_exact_assessment_retry_replays_same_logical_result(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        first = assess(client, case_id, key="same-key")
        second = assess(client, case_id, key="same-key")

        assert first.status_code == 200
        assert second.status_code == 200
        assert second.json()["assessment_id"] == first.json()["assessment_id"]
        assert second.json()["idempotent_replay"] is True

        with app.state.database.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Assessment)
                    .where(Assessment.case_id == case_id)
                )
                == 1
            )


def test_same_assessment_key_with_changed_revision_conflicts(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        assert assess(client, case_id, key="same-key").status_code == 200
        assert append_event(client, case_id).status_code == 200

        changed = assess(
            client,
            case_id,
            key="same-key",
            expected_revision=2,
        )

        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "idempotency_conflict"


def test_stale_revision_is_rejected_before_extraction(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        response = assess(client, case_id, expected_revision=2)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Assessment)) == 0


def test_second_owner_cannot_assess_or_retrieve(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as owner, TestClient(app) as stranger:
        bootstrap(owner)
        bootstrap(stranger)
        case_id = create_case(owner).json()["case_id"]

        forbidden_assess = assess(stranger, case_id)
        forbidden_latest = stranger.get(f"/cases/{case_id}/assessments/latest")

        assert forbidden_assess.status_code == 404
        assert forbidden_latest.status_code == 404


def test_assessment_post_requires_csrf(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        response = client.post(
            f"/cases/{case_id}/assess",
            headers={"Idempotency-Key": "assess-no-csrf"},
            json={"expected_revision": 1},
        )

        assert response.status_code == 403
        assert response.json()["detail"]["code"] == "csrf_rejected"


def test_latest_without_assessment_has_clean_not_found_response(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        response = client.get(f"/cases/{case_id}/assessments/latest")

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "assessment_not_found"


def test_unsupported_mock_input_persists_unable_to_assess(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(
            client,
            text="Completely unrelated arbitrary conversation.",
        ).json()["case_id"]

        response = assess(client, case_id)

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "unable_to_assess"
        assert body["reason_codes"] == ["mock_input_unsupported"]
        assert body["evidence"] == []


def test_case_delete_removes_assessment_and_evidence_but_tombstones_retry(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(tmp_path))

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        response = assess(client, case_id, key="delete-assessment")
        assert response.status_code == 200
        assert response.json()["evidence"]

        deleted = client.delete(f"/cases/{case_id}", headers=HEADERS)
        assert deleted.status_code == 204

        with app.state.database.session_factory() as session:
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(Assessment)
                    .where(Assessment.case_id == case_id)
                )
                == 0
            )
            assert session.scalar(select(func.count()).select_from(AssessmentEvidence)) == 0
            record = session.scalar(
                select(AssessmentIdempotencyRecord).where(
                    AssessmentIdempotencyRecord.request_key == "delete-assessment"
                )
            )
            assert record is not None
            assert record.target_case_id is None
            assert record.assessment_id is None
            assert record.resource_deleted is True


def test_production_rejects_development_mock_extractor(tmp_path: Path) -> None:
    settings = Settings(
        environment=Environment.PRODUCTION,
        database_path=tmp_path / "production.sqlite3",
        trusted_origin="https://scamflow.example",
    )

    with pytest.raises(
        ValueError,
        match="development mock extractor cannot be used in production",
    ):
        create_app(
            settings,
            extractor=DevelopmentMockExtractor(),
        )


def test_latest_assessment_deterministic_ordering_same_second_across_revisions(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assessments across revisions in the same second must return the latest revision."""
    fixed_time = 1_800_000_000
    app = create_app(make_settings(tmp_path), clock=lambda: fixed_time)

    # Force UUIDs so that earlier revision gets higher lexical value
    # rev 1 -> zzzz..., rev 2 -> aaaa...
    # Under old created_at DESC, id DESC, rev 1 would incorrectly win!
    generated_ids = [
        "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]
    id_iter = iter(generated_ids)
    monkeypatch.setattr(
        "backend.scamflow.assessment_services._new_public_id",
        lambda: next(id_iter),
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        # 1. Assess revision 1 (gets id zzzz...)
        first = assess(client, case_id, key="assess-rev1", expected_revision=1)
        assert first.status_code == 200
        assert first.json()["assessment_id"] == "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
        assert first.json()["assessed_revision"] == 1

        # 2. Append event -> advances case to revision 2
        appended = append_event(client, case_id)
        assert appended.status_code == 200
        assert appended.json()["result_revision"] == 2

        # 3. Assess revision 2 (gets id aaaa...) in same second
        second = assess(client, case_id, key="assess-rev2", expected_revision=2)
        assert second.status_code == 200
        assert second.json()["assessment_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert second.json()["assessed_revision"] == 2

        # 4. Query latest assessment
        latest = client.get(f"/cases/{case_id}/assessments/latest", headers=HEADERS)
        assert latest.status_code == 200
        data = latest.json()
        assert data["assessed_revision"] == 2
        assert data["assessment_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert data["is_current"] is True


def test_latest_assessment_deterministic_ordering_same_second_same_revision(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Assessments for the same revision in the same second must return the newest attempt."""
    fixed_time = 1_800_000_000
    app = create_app(make_settings(tmp_path), clock=lambda: fixed_time)

    # Force UUIDs so first attempt gets zzzz..., second attempt gets aaaa...
    # Under old created_at DESC, id DESC, first attempt would win!
    generated_ids = [
        "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz",
        "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    ]
    id_iter = iter(generated_ids)
    monkeypatch.setattr(
        "backend.scamflow.assessment_services._new_public_id",
        lambda: next(id_iter),
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        # 1. First assess revision 1 (gets zzzz...)
        first = assess(client, case_id, key="assess-attempt-1", expected_revision=1)
        assert first.status_code == 200
        assert first.json()["assessment_id"] == "zzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"

        # 2. Second assess revision 1 with new key (reassessment attempt, gets aaaa...)
        second = assess(client, case_id, key="assess-attempt-2", expected_revision=1)
        assert second.status_code == 200
        assert second.json()["assessment_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"

        # 3. Query latest assessment
        latest = client.get(f"/cases/{case_id}/assessments/latest", headers=HEADERS)
        assert latest.status_code == 200
        data = latest.json()
        assert data["assessed_revision"] == 1
        assert data["assessment_id"] == "aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa"
        assert data["is_current"] is True



def test_fake_refund_assessment_persists_exact_unicode_evidence_and_alert(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(tmp_path))
    text = (
        "İ 📩 Customer support: your refund has been approved. "
        "Pay a processing fee to receive it."
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(
            client,
            text=text,
            purpose="Refund processing",
        ).json()["case_id"]

        response = assess(client, case_id, key="fake-refund-assessment")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "high_risk_indicators"
        assert body["reason_codes"] == ["refund_linked_to_payment_credentials_or_mismatch"]
        assert body["alert"]["visible"] is True
        assert "support_identity_claim" in body["tactics_used"]
        assert "claimed_refund" in body["tactics_used"]
        assert "advance_payment_request" in body["tactics_used"]
        assert body["evidence"]
        assert all(item["event_id"] == "evt-1" for item in body["evidence"])
        assert all(item["source_order"] == 1 for item in body["evidence"])
        assert all(
            text[item["start_offset"] : item["end_offset"]] == item["quote"]
            for item in body["evidence"]
        )
        support = next(
            item for item in body["evidence"] if item["tactic"] == "support_identity_claim"
        )
        assert support["quote"] == "Customer support"
        assert support["start_offset"] == text.index("Customer support")


def test_refund_purpose_outgoing_payment_mismatch_persists_review_evidence(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(tmp_path))
    text = "Transfer money to account 123 to complete the requested resolution."

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(
            client,
            text=text,
            purpose="Refund resolution",
        ).json()["case_id"]

        response = assess(client, case_id, key="refund-purpose-mismatch")

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "needs_clarification_or_review"
        assert body["reason_codes"] == ["refund_purpose_outgoing_payment_mismatch"]
        assert "not proof of fraud" in body["explanation"]
        evidence = next(
            item for item in body["evidence"] if item["tactic"] == "outgoing_payment_request"
        )
        assert evidence["event_id"] == "evt-1"
        assert evidence["source_order"] == 1
        assert evidence["quote"] == "Transfer money"
        assert text[evidence["start_offset"] : evidence["end_offset"]] == evidence["quote"]
