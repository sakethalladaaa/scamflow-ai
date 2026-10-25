from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.scamflow.app import create_app
from backend.scamflow.models import (
    Assessment,
    ReviewRequest,
    ReviewRequestIdempotencyRecord,
)
from backend.scamflow.security import CSRF_HEADER_NAME, REVIEWER_HEADER_NAME
from backend.scamflow.settings import Environment, Settings

ORIGIN = "http://127.0.0.1:8000"
OWNER_HEADERS = {"Origin": ORIGIN, CSRF_HEADER_NAME: "1"}
REVIEWER_TOKEN = "test-reviewer-token-for-local-suite"
REVIEWER_HEADERS = {REVIEWER_HEADER_NAME: REVIEWER_TOKEN}


def make_settings(tmp_path: Path, *, reviewer_token: str | None = REVIEWER_TOKEN) -> Settings:
    return Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "review-requests.sqlite3",
        trusted_origin=ORIGIN,
        reviewer_token=reviewer_token,
    )


def bootstrap(client: TestClient) -> None:
    response = client.post("/session", headers=OWNER_HEADERS)
    assert response.status_code == 200


def create_case(
    client: TestClient,
    *,
    text: str = "Pay a processing fee. Reference number RF-1.",
    purpose: str = "Refund",
    key: str = "create-case",
):
    return client.post(
        "/cases",
        headers={**OWNER_HEADERS, "Idempotency-Key": key},
        json={
            "consent": True,
            "payment_context": {"stated_purpose": purpose},
            "events": [
                {
                    "event_id": "evt-1",
                    "channel": "sms",
                    "text": text,
                    "source_order": 1,
                }
            ],
        },
    )


def assess(client: TestClient, case_id: str, *, key: str = "assess-case", revision: int = 1):
    return client.post(
        f"/cases/{case_id}/assess",
        headers={**OWNER_HEADERS, "Idempotency-Key": key},
        json={"expected_revision": revision},
    )


def request_review(
    client: TestClient,
    case_id: str,
    *,
    assessment_id: str,
    key: str = "review-request",
    revision: int = 1,
):
    return client.post(
        f"/cases/{case_id}/review-requests",
        headers={**OWNER_HEADERS, "Idempotency-Key": key},
        json={"assessment_id": assessment_id, "expected_revision": revision},
    )


def test_owner_creates_and_reads_only_own_review_status(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as owner:
        bootstrap(owner)
        case_id = create_case(owner).json()["case_id"]
        assessment = assess(owner, case_id).json()
        assert assessment["state"] == "needs_clarification_or_review"

        created = request_review(owner, case_id, assessment_id=assessment["assessment_id"])
        assert created.status_code == 201
        body = created.json()
        assert body["status"] == "open"
        assert body["assessment_id"] == assessment["assessment_id"]
        assert body["assessed_revision"] == 1
        assert body["idempotent_replay"] is False
        assert body["existing_open_request"] is False
        assert "reviewer_note" not in body

        status = owner.get(f"/cases/{case_id}/review-requests/{body['review_request_id']}")
        assert status.status_code == 200
        assert status.json()["status"] == "open"
        assert "reviewer_note" not in status.json()


def test_owner_create_preserves_csrf_and_idempotency_requirements(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]
        assessment_id = assess(client, case_id).json()["assessment_id"]
        payload = {"assessment_id": assessment_id, "expected_revision": 1}

        no_csrf = client.post(
            f"/cases/{case_id}/review-requests",
            headers={"Idempotency-Key": "without-csrf"},
            json=payload,
        )
        assert no_csrf.status_code == 403
        assert no_csrf.json()["detail"]["code"] == "csrf_rejected"

        no_key = client.post(
            f"/cases/{case_id}/review-requests",
            headers=OWNER_HEADERS,
            json=payload,
        )
        assert no_key.status_code == 422
        assert no_key.json()["detail"]["code"] == "idempotency_key_required"


def test_cross_owner_cannot_create_or_read_another_owners_review(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]
        assessment = assess(client, case_id).json()
        created = request_review(client, case_id, assessment_id=assessment["assessment_id"]).json()
        assert client.cookies.get("scamflow_session") is not None

        client.cookies.clear()
        bootstrap(client)
        status = client.get(
            f"/cases/{case_id}/review-requests/{created['review_request_id']}"
        )
        assert status.status_code == 404
        assert status.json()["detail"]["code"] == "review_request_not_found"

        denied = request_review(
            client,
            case_id,
            assessment_id=assessment["assessment_id"],
            key="cross-owner-request",
        )
        assert denied.status_code == 404
        assert denied.json()["detail"]["code"] == "case_not_found"


def test_reviewer_authorization_is_separate_and_required(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        bootstrap(client)
        no_token = client.get("/reviewer/review-requests")
        assert no_token.status_code == 401
        assert no_token.json()["detail"]["code"] == "reviewer_auth_required"

        wrong_token = client.get(
            "/reviewer/review-requests",
            headers={REVIEWER_HEADER_NAME: "incorrect-token"},
        )
        assert wrong_token.status_code == 401
        assert wrong_token.json()["detail"]["code"] == "reviewer_auth_required"

    disabled_app = create_app(make_settings(tmp_path / "disabled", reviewer_token=None))
    with TestClient(disabled_app) as reviewer:
        unavailable = reviewer.get("/reviewer/review-requests", headers=REVIEWER_HEADERS)
        assert unavailable.status_code == 503
        assert unavailable.json()["detail"]["code"] == "reviewer_access_unconfigured"


def test_create_is_idempotent_and_deduplicates_other_open_request_keys(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]
        assessment_id = assess(client, case_id).json()["assessment_id"]

        first = request_review(client, case_id, assessment_id=assessment_id, key="review-a")
        replay = request_review(client, case_id, assessment_id=assessment_id, key="review-a")
        duplicate = request_review(client, case_id, assessment_id=assessment_id, key="review-b")

        assert first.status_code == 201
        assert replay.status_code == 200
        assert replay.json()["review_request_id"] == first.json()["review_request_id"]
        assert replay.json()["idempotent_replay"] is True
        assert duplicate.status_code == 200
        assert duplicate.json()["review_request_id"] == first.json()["review_request_id"]
        assert duplicate.json()["existing_open_request"] is True

        changed = client.post(
            f"/cases/{case_id}/review-requests",
            headers={**OWNER_HEADERS, "Idempotency-Key": "review-a"},
            json={"assessment_id": assessment_id, "expected_revision": 2},
        )
        assert changed.status_code == 409
        assert changed.json()["detail"]["code"] == "idempotency_conflict"

        with app.state.database.session_factory() as session:
            count = session.scalar(select(func.count()).select_from(ReviewRequest))
            assert count == 1


def test_only_current_uncertain_assessments_are_eligible(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(
            client,
            text="Your appointment is confirmed. Reference number ABC-123.",
            purpose="Appointment details",
        ).json()["case_id"]
        assessment = assess(client, case_id).json()
        assert assessment["state"] == "no_strong_indicators"

        denied = request_review(client, case_id, assessment_id=assessment["assessment_id"])
        assert denied.status_code == 409
        assert denied.json()["detail"]["code"] == "review_not_available"

        unsupported_case = create_case(
            client,
            text="Are you free to meet later?",
            purpose="Personal conversation",
            key="unsupported-case",
        ).json()["case_id"]
        unsupported_assessment = assess(
            client,
            unsupported_case,
            key="unsupported-assessment",
        ).json()
        assert unsupported_assessment["state"] == "unable_to_assess"
        eligible = request_review(
            client,
            unsupported_case,
            assessment_id=unsupported_assessment["assessment_id"],
            key="unsupported-review",
        )
        assert eligible.status_code == 201

        appended = client.post(
            f"/cases/{case_id}/events",
            headers={**OWNER_HEADERS, "Idempotency-Key": "append-after-assessment"},
            json={
                "expected_revision": 1,
                "events": [
                    {
                        "event_id": "evt-2",
                        "channel": "sms",
                        "text": "Additional context.",
                        "source_order": 2,
                    }
                ],
            },
        )
        assert appended.status_code == 200
        stale = request_review(
            client,
            case_id,
            assessment_id=assessment["assessment_id"],
            key="stale-review",
            revision=1,
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["code"] == "revision_conflict"


def test_reviewer_queue_works_without_owner_cookie_and_lists_only_open(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as owner:
        bootstrap(owner)
        case_id = create_case(owner).json()["case_id"]
        assessment = assess(owner, case_id).json()
        created = request_review(owner, case_id, assessment_id=assessment["assessment_id"]).json()

        owner_cookie = owner.cookies.get("scamflow_session")
        assert owner_cookie is not None
        owner.cookies.clear()
        response = owner.get("/reviewer/review-requests", headers=REVIEWER_HEADERS)
        assert response.status_code == 200
        body = response.json()
        assert body["total"] == 1
        assert body["items"][0]["review_request_id"] == created["review_request_id"]
        assert body["items"][0]["assessment_state"] == assessment["state"]
        assert body["items"][0]["is_current"] is True
        assert "events" not in body["items"][0]

        owner.cookies.set("scamflow_session", owner_cookie)
        appended = owner.post(
            f"/cases/{case_id}/events",
            headers={**OWNER_HEADERS, "Idempotency-Key": "append-after-review-request"},
            json={
                "expected_revision": 1,
                "events": [
                    {
                        "event_id": "evt-2",
                        "channel": "sms",
                        "text": "A later message.",
                        "source_order": 2,
                    }
                ],
            },
        )
        assert appended.status_code == 200
        owner.cookies.clear()
        stale_queue = owner.get("/reviewer/review-requests", headers=REVIEWER_HEADERS)
        assert stale_queue.json()["items"][0]["is_current"] is False


def test_reviewer_detail_uses_exact_persisted_assessment_evidence(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    source = "İ 📩 Pay a processing fee. Reference number RF-1."
    with TestClient(app) as owner:
        bootstrap(owner)
        case_id = create_case(owner, text=source).json()["case_id"]
        assessment = assess(owner, case_id).json()
        created = request_review(owner, case_id, assessment_id=assessment["assessment_id"]).json()

        owner.cookies.clear()
        detail = owner.get(
            f"/reviewer/review-requests/{created['review_request_id']}",
            headers=REVIEWER_HEADERS,
        )
    assert detail.status_code == 200
    body = detail.json()
    snapshot = body["assessment"]
    assert snapshot["assessment_id"] == assessment["assessment_id"]
    assert snapshot["state"] == assessment["state"]
    assert snapshot["explanation"] == assessment["explanation"]
    assert snapshot["limitations"] == assessment["limitations"]
    assert snapshot["suggested_next_action"] == assessment["suggested_next_action"]
    assert snapshot["alert"] == assessment["alert"]
    stored_evidence = next(
        item for item in assessment["evidence"] if item["quote"] == "Pay a processing fee"
    )
    evidence = next(
        item for item in snapshot["evidence"] if item["quote"] == stored_evidence["quote"]
    )
    assert evidence["quote"] == stored_evidence["quote"] == "Pay a processing fee"
    assert {key: evidence[key] for key in stored_evidence} == stored_evidence
    assert evidence["source_text"] == source
    assert evidence["source_text"][evidence["start_offset"] : evidence["end_offset"]] == evidence[
        "quote"
    ]
    assert evidence["start_offset"] == source.index("Pay a processing fee")


def test_reviewer_resolution_persists_bounded_outcome_and_note_is_private(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as owner:
        bootstrap(owner)
        case_id = create_case(owner).json()["case_id"]
        assessment_id = assess(owner, case_id).json()["assessment_id"]
        created = request_review(owner, case_id, assessment_id=assessment_id).json()
        request_id = created["review_request_id"]

        owner_cookie = owner.cookies.get("scamflow_session")
        assert owner_cookie is not None
        owner.cookies.clear()
        resolved = owner.post(
            f"/reviewer/review-requests/{request_id}/resolve",
            headers={**REVIEWER_HEADERS, "Idempotency-Key": "resolve-1"},
            json={"outcome": "follow_up", "reviewer_note": "Contact the requester."},
        )
        replay = owner.post(
            f"/reviewer/review-requests/{request_id}/resolve",
            headers={**REVIEWER_HEADERS, "Idempotency-Key": "resolve-1"},
            json={"outcome": "follow_up", "reviewer_note": "Contact the requester."},
        )
        assert resolved.status_code == 200
        assert resolved.json()["status"] == "resolved"
        assert resolved.json()["outcome"] == "follow_up"
        assert resolved.json()["reviewer_note"] == "Contact the requester."
        assert replay.status_code == 200
        assert replay.json()["idempotent_replay"] is True
        assert replay.json()["review_request_id"] == resolved.json()["review_request_id"]

        owner.cookies.set("scamflow_session", owner_cookie)
        owner_status = owner.get(f"/cases/{case_id}/review-requests/{request_id}")
        assert owner_status.status_code == 200
        assert owner_status.json()["outcome"] == "follow_up"
        assert "reviewer_note" not in owner_status.json()

        owner.cookies.clear()
        queue = owner.get("/reviewer/review-requests", headers=REVIEWER_HEADERS)
        detail = owner.get(
            f"/reviewer/review-requests/{request_id}",
            headers=REVIEWER_HEADERS,
        )
        assert queue.json()["total"] == 0
        assert detail.json()["reviewer_note"] == "Contact the requester."

        invalid = owner.post(
            f"/reviewer/review-requests/{request_id}/resolve",
            headers={**REVIEWER_HEADERS, "Idempotency-Key": "invalid-resolution"},
            json={"outcome": "fraud_confirmed"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "validation_error"


def test_review_request_and_resolution_survive_app_recreation(tmp_path: Path) -> None:
    settings = make_settings(tmp_path)
    first_app = create_app(settings)
    with TestClient(first_app) as owner:
        bootstrap(owner)
        case_id = create_case(owner).json()["case_id"]
        assessment_id = assess(owner, case_id).json()["assessment_id"]
        created = request_review(owner, case_id, assessment_id=assessment_id).json()
        cookie = owner.cookies.get("scamflow_session")
        assert cookie is not None

    second_app = create_app(settings)
    with TestClient(second_app) as owner:
        owner.cookies.set("scamflow_session", cookie)
        status = owner.get(
            f"/cases/{case_id}/review-requests/{created['review_request_id']}"
        )
        assert status.status_code == 200
        assert status.json()["status"] == "open"

    with TestClient(second_app) as reviewer:
        queue = reviewer.get("/reviewer/review-requests", headers=REVIEWER_HEADERS)
    assert queue.status_code == 200
    assert queue.json()["items"][0]["review_request_id"] == created["review_request_id"]


def test_expired_case_review_is_hidden_from_owner_and_reviewer(tmp_path: Path) -> None:
    current_time = [1_800_000_000]
    settings = Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "expired-review.sqlite3",
        trusted_origin=ORIGIN,
        case_retention_seconds=60,
        session_ttl_seconds=120,
        reviewer_token=REVIEWER_TOKEN,
    )
    app = create_app(settings, clock=lambda: current_time[0])
    with TestClient(app) as owner:
        bootstrap(owner)
        case_id = create_case(owner).json()["case_id"]
        assessment_id = assess(owner, case_id).json()["assessment_id"]
        created = request_review(owner, case_id, assessment_id=assessment_id).json()

        current_time[0] += 61
        owner_status = owner.get(
            f"/cases/{case_id}/review-requests/{created['review_request_id']}"
        )
        assert owner_status.status_code == 404

        owner.cookies.clear()
        reviewer_queue = owner.get("/reviewer/review-requests", headers=REVIEWER_HEADERS)
        reviewer_detail = owner.get(
            f"/reviewer/review-requests/{created['review_request_id']}",
            headers=REVIEWER_HEADERS,
        )
        assert reviewer_queue.status_code == 200
        assert reviewer_queue.json()["total"] == 0
        assert reviewer_detail.status_code == 404

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(ReviewRequest)) == 1


def test_delete_cascades_review_data_and_leaves_only_retry_tombstone(tmp_path: Path) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as owner:
        bootstrap(owner)
        case_id = create_case(owner).json()["case_id"]
        assessment_id = assess(owner, case_id).json()["assessment_id"]
        created = request_review(owner, case_id, assessment_id=assessment_id).json()

        deleted = owner.delete(f"/cases/{case_id}", headers=OWNER_HEADERS)
        assert deleted.status_code == 204
        status = owner.get(
            f"/cases/{case_id}/review-requests/{created['review_request_id']}"
        )
        assert status.status_code == 404

        retry = request_review(
            owner,
            case_id,
            assessment_id=assessment_id,
            key="review-request",
        )
        assert retry.status_code == 409
        assert retry.json()["detail"]["code"] == "idempotency_resource_deleted"

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(ReviewRequest)) == 0
            tombstone = session.scalar(
                select(ReviewRequestIdempotencyRecord).where(
                    ReviewRequestIdempotencyRecord.request_key == "review-request"
                )
            )
            assert tombstone is not None
            assert tombstone.resource_deleted is True
            assert tombstone.target_case_id is None
            assert tombstone.review_request_id is None
            assert tombstone.operation_scope == "create_review_request"
            assert case_id not in tombstone.operation_scope
            assert session.scalar(select(func.count()).select_from(Assessment)) == 0

    with TestClient(app) as reviewer:
        queue = reviewer.get("/reviewer/review-requests", headers=REVIEWER_HEADERS)
    assert queue.status_code == 200
    assert queue.json()["total"] == 0


def test_digital_arrest_and_fake_refund_assessments_remain_backend_controlled(
    tmp_path: Path,
) -> None:
    app = create_app(make_settings(tmp_path))
    with TestClient(app) as client:
        bootstrap(client)
        cases = [
            (
                "I am a police officer. You will be arrested. Stay on the call.",
                "Verification",
            ),
            (
                "Customer support: your refund has been approved. "
                "Pay a processing fee to receive it.",
                "Refund processing",
            ),
        ]
        for index, (text, purpose) in enumerate(cases, start=1):
            case_id = create_case(
                client,
                text=text,
                purpose=purpose,
                key=f"create-regression-{index}",
            ).json()["case_id"]
            assessment = assess(client, case_id, key=f"assess-regression-{index}").json()
            assert assessment["state"] == "high_risk_indicators"
            before = client.get(f"/cases/{case_id}/assessments/latest").json()

            denied = request_review(
                client,
                case_id,
                assessment_id=assessment["assessment_id"],
                key=f"review-regression-{index}",
            )
            assert denied.status_code == 409
            assert denied.json()["detail"]["code"] == "review_not_available"
            after = client.get(f"/cases/{case_id}/assessments/latest").json()
            assert after["state"] == before["state"]
            assert after["evidence"] == before["evidence"]

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(ReviewRequest)) == 0
