from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.scamflow.app import create_app
from backend.scamflow.detection import CaseSnapshot, DevelopmentMockExtractor
from backend.scamflow.models import AlertMemory, AssessmentAlert
from backend.scamflow.security import CSRF_HEADER_NAME
from backend.scamflow.settings import Environment, Settings

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"Origin": ORIGIN, CSRF_HEADER_NAME: "1"}


def test_alert_suppression_then_material_escalation(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            environment=Environment.TEST,
            database_path=tmp_path / "alerts.sqlite3",
            trusted_origin=ORIGIN,
        )
    )
    with TestClient(app) as client:
        assert client.post("/session", headers=HEADERS).status_code == 200
        created = client.post(
            "/cases",
            headers={**HEADERS, "Idempotency-Key": "create"},
            json={
                "consent": True,
                "payment_context": {"stated_purpose": "Refund"},
                "events": [{
                    "event_id": "e1", "channel": "sms",
                    "text": "Pay a processing fee. Reference number RF-1.", "source_order": 1,
                }],
            },
        )
        case_id = created.json()["case_id"]
        first = client.post(
            f"/cases/{case_id}/assess",
            headers={**HEADERS, "Idempotency-Key": "assess-1"},
            json={"expected_revision": 1},
        ).json()
        assert first["state"] == "needs_clarification_or_review"
        assert first["alert"] == {
            "visible": True,
            "reason": "initial_material_warning",
            "prior_warning_state": None,
        }

        append = client.post(
            f"/cases/{case_id}/events",
            headers={**HEADERS, "Idempotency-Key": "append-benign"},
            json={"expected_revision": 1, "events": [{
                "event_id": "e2", "channel": "sms",
                "text": "Appointment confirmed.", "source_order": 2,
            }]},
        )
        assert append.status_code == 200
        repeated = client.post(
            f"/cases/{case_id}/assess",
            headers={**HEADERS, "Idempotency-Key": "assess-2"},
            json={"expected_revision": 2},
        ).json()
        assert repeated["alert"]["visible"] is False
        assert repeated["alert"]["reason"] == "unchanged_warning_suppressed"

        assert client.post(
            f"/cases/{case_id}/events",
            headers={**HEADERS, "Idempotency-Key": "append-refund"},
            json={"expected_revision": 2, "events": [{
                "event_id": "e3", "channel": "sms",
                "text": "Your refund has been approved.", "source_order": 3,
            }]},
        ).status_code == 200
        escalated = client.post(
            f"/cases/{case_id}/assess",
            headers={**HEADERS, "Idempotency-Key": "assess-3"},
            json={"expected_revision": 3},
        ).json()
        assert escalated["state"] == "high_risk_indicators"
        assert escalated["alert"]["visible"] is True
        assert escalated["alert"]["reason"] == "material_risk_escalation"

        replay = client.post(
            f"/cases/{case_id}/assess",
            headers={**HEADERS, "Idempotency-Key": "assess-3"},
            json={"expected_revision": 3},
        ).json()
        assert replay["assessment_id"] == escalated["assessment_id"]
        assert replay["alert"] == escalated["alert"]

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(AlertMemory)) == 1
            assert session.scalar(select(func.count()).select_from(AssessmentAlert)) == 3

        assert client.delete(f"/cases/{case_id}", headers=HEADERS).status_code == 204
        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(AlertMemory)) == 0
            assert session.scalar(select(func.count()).select_from(AssessmentAlert)) == 0


class _FailAfterFirstRevision:
    mode = "development_mock"
    version = "revision-aware-failure-v1"

    def __init__(self) -> None:
        self.delegate = DevelopmentMockExtractor()

    def extract(self, snapshot: CaseSnapshot) -> object:
        if snapshot.revision > 1:
            raise RuntimeError("synthetic provider failure")
        return self.delegate.extract(snapshot)


def test_extraction_failure_preserves_prior_warning_memory(tmp_path: Path) -> None:
    app = create_app(
        Settings(
            environment=Environment.TEST,
            database_path=tmp_path / "failure-memory.sqlite3",
            trusted_origin=ORIGIN,
        ),
        extractor=_FailAfterFirstRevision(),
    )
    with TestClient(app) as client:
        client.post("/session", headers=HEADERS)
        case_id = client.post(
            "/cases",
            headers={**HEADERS, "Idempotency-Key": "create"},
            json={
                "consent": True,
                "payment_context": {"stated_purpose": "Refund"},
                "events": [{
                    "event_id": "e1", "channel": "sms",
                    "text": "Pay a processing fee. Reference number RF-1.", "source_order": 1,
                }],
            },
        ).json()["case_id"]
        first = client.post(
            f"/cases/{case_id}/assess",
            headers={**HEADERS, "Idempotency-Key": "assess-1"},
            json={"expected_revision": 1},
        )
        assert first.json()["state"] == "needs_clarification_or_review"
        client.post(
            f"/cases/{case_id}/events",
            headers={**HEADERS, "Idempotency-Key": "append"},
            json={"expected_revision": 1, "events": [{
                "event_id": "e2", "channel": "sms", "text": "New context.", "source_order": 2,
            }]},
        )
        failed = client.post(
            f"/cases/{case_id}/assess",
            headers={**HEADERS, "Idempotency-Key": "assess-2"},
            json={"expected_revision": 2},
        ).json()
        assert failed["state"] == "unable_to_assess"
        assert failed["alert"] == {
            "visible": True,
            "reason": "extraction_failure_prior_warning_preserved",
            "prior_warning_state": "needs_clarification_or_review",
        }
        with app.state.database.session_factory() as session:
            memory = session.get(AlertMemory, case_id)
            assert memory is not None
            assert memory.warning_state == "needs_clarification_or_review"
            assert memory.source_revision == 1
