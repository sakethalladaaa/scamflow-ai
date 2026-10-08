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
):
    return client.post(
        "/cases",
        headers={**HEADERS, "Idempotency-Key": key},
        json={
            "consent": True,
            "payment_context": {
                "stated_purpose": "Verification",
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
