from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Event

from fastapi.testclient import TestClient
from sqlalchemy import func, select

from backend.scamflow.app import create_app
from backend.scamflow.detection import CaseSnapshot
from backend.scamflow.models import Assessment
from backend.scamflow.security import CSRF_HEADER_NAME
from backend.scamflow.settings import Environment, Settings

ORIGIN = "http://127.0.0.1:8000"
HEADERS = {"Origin": ORIGIN, CSRF_HEADER_NAME: "1"}


class FakeClock:
    def __init__(self, value: int = 1_800_000_000) -> None:
        self.value = value

    def __call__(self) -> int:
        return self.value

    def advance(self, seconds: int) -> None:
        self.value += seconds


class MalformedExtractor:
    mode = "test_malformed"
    version = "v1"

    def extract(self, _snapshot: CaseSnapshot) -> object:
        return {
            "status": "ok",
            "observations": [
                {
                    "tactic": "authority_claim",
                    "event_id": "missing-event",
                    "quote": "invented evidence",
                    "start": 0,
                    "end": 17,
                    "context": "asserted",
                }
            ],
        }


class FailingExtractor:
    mode = "test_failure"
    version = "v1"

    def extract(self, _snapshot: CaseSnapshot) -> object:
        raise RuntimeError("synthetic secret extractor failure")


class BlockingExtractor:
    mode = "test_blocking"
    version = "v1"

    def __init__(self) -> None:
        self.started = Event()
        self.release = Event()

    def extract(self, snapshot: CaseSnapshot) -> object:
        self.started.set()
        assert self.release.wait(timeout=5)
        return {
            "status": "ok",
            "observations": [],
        }


class TimeoutExtractor:
    mode = "test_timeout"
    version = "v1"

    def __init__(self) -> None:
        self.release = Event()

    def extract(self, _snapshot: CaseSnapshot) -> object:
        self.release.wait(timeout=5)
        return {"status": "ok", "observations": []}


class BarrierExtractor:
    mode = "test_barrier"
    version = "v1"

    def __init__(self, barrier: Barrier) -> None:
        self.barrier = barrier

    def extract(self, _snapshot: CaseSnapshot) -> object:
        self.barrier.wait(timeout=5)
        return {"status": "ok", "observations": []}


def make_settings(tmp_path: Path, **overrides: object) -> Settings:
    values: dict[str, object] = {
        "environment": Environment.TEST,
        "database_path": tmp_path / "assessment-races.sqlite3",
        "trusted_origin": ORIGIN,
    }
    values.update(overrides)
    return Settings(**values)


def bootstrap(client: TestClient) -> None:
    assert client.post("/session", headers=HEADERS).status_code == 200


def create_case(client: TestClient):
    return client.post(
        "/cases",
        headers={**HEADERS, "Idempotency-Key": "create-1"},
        json={
            "consent": True,
            "payment_context": {
                "stated_purpose": "Verification",
                "amount": "5000",
            },
            "events": [
                {
                    "event_id": "evt-1",
                    "channel": "sms",
                    "text": "Appointment confirmed. Reference number ABC-123.",
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


def append_event(client: TestClient, case_id: str):
    return client.post(
        f"/cases/{case_id}/events",
        headers={**HEADERS, "Idempotency-Key": "append-race"},
        json={
            "expected_revision": 1,
            "events": [
                {
                    "event_id": "evt-2",
                    "channel": "sms",
                    "text": "Additional evidence",
                    "source_order": 2,
                }
            ],
        },
    )


def test_malformed_extraction_persists_explicit_unable_to_assess(
    tmp_path: Path,
) -> None:
    app = create_app(
        make_settings(tmp_path),
        extractor=MalformedExtractor(),
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        response = assess(client, case_id)

        assert response.status_code == 200
        body = response.json()
        assert body["state"] == "unable_to_assess"
        assert body["reason_codes"] == ["invalid_extraction_evidence"]
        assert body["evidence"] == []
        assert "invented evidence" not in response.text


def test_extractor_failure_is_safe_unable_to_assess(
    tmp_path: Path,
) -> None:
    app = create_app(
        make_settings(tmp_path),
        extractor=FailingExtractor(),
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        response = assess(client, case_id)

        assert response.status_code == 200
        assert response.json()["state"] == "unable_to_assess"
        assert response.json()["reason_codes"] == ["extraction_failed"]
        assert "synthetic secret extractor failure" not in response.text


def test_extractor_timeout_is_unable_to_assess_not_low_risk(
    tmp_path: Path,
) -> None:
    extractor = TimeoutExtractor()
    app = create_app(
        make_settings(tmp_path, assessment_timeout_seconds=0.01),
        extractor=extractor,
    )

    try:
        with TestClient(app) as client:
            bootstrap(client)
            case_id = create_case(client).json()["case_id"]

            response = assess(client, case_id)

            assert response.status_code == 200
            assert response.json()["state"] == "unable_to_assess"
            assert response.json()["reason_codes"] == ["extraction_timeout"]
    finally:
        extractor.release.set()


def test_append_during_extraction_prevents_stale_assessment_commit(
    tmp_path: Path,
) -> None:
    extractor = BlockingExtractor()
    app = create_app(
        make_settings(tmp_path),
        extractor=extractor,
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(assess, client, case_id)
            assert extractor.started.wait(timeout=5)

            appended = append_event(client, case_id)
            assert appended.status_code == 200
            assert appended.json()["result_revision"] == 2

            extractor.release.set()
            response = future.result(timeout=5)

        assert response.status_code == 409
        assert response.json()["detail"]["code"] == "revision_conflict"

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Assessment)) == 0


def test_delete_during_extraction_prevents_orphan_assessment(
    tmp_path: Path,
) -> None:
    extractor = BlockingExtractor()
    app = create_app(
        make_settings(tmp_path),
        extractor=extractor,
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(assess, client, case_id)
            assert extractor.started.wait(timeout=5)

            deleted = client.delete(f"/cases/{case_id}", headers=HEADERS)
            assert deleted.status_code == 204

            extractor.release.set()
            response = future.result(timeout=5)

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "case_not_found"

        with app.state.database.session_factory() as session:
            assert session.scalar(select(func.count()).select_from(Assessment)) == 0


def test_case_expiry_during_extraction_prevents_commit(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    extractor = BlockingExtractor()
    app = create_app(
        make_settings(tmp_path, case_retention_seconds=60),
        clock=clock,
        extractor=extractor,
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(assess, client, case_id)
            assert extractor.started.wait(timeout=5)

            clock.advance(61)
            extractor.release.set()
            response = future.result(timeout=5)

        assert response.status_code == 404
        assert response.json()["detail"]["code"] == "case_not_found"


def test_session_expiry_during_extraction_prevents_commit(
    tmp_path: Path,
) -> None:
    clock = FakeClock()
    extractor = BlockingExtractor()
    app = create_app(
        make_settings(tmp_path, session_ttl_seconds=60),
        clock=clock,
        extractor=extractor,
    )

    with TestClient(app) as client:
        bootstrap(client)
        case_id = create_case(client).json()["case_id"]

        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(assess, client, case_id)
            assert extractor.started.wait(timeout=5)

            clock.advance(61)
            extractor.release.set()
            response = future.result(timeout=5)

        assert response.status_code == 401
        assert response.json()["detail"]["code"] == "session_invalid"


def test_concurrent_identical_assessment_requests_are_one_logical_result(
    tmp_path: Path,
) -> None:
    barrier = Barrier(2)
    app = create_app(
        make_settings(tmp_path),
        extractor=BarrierExtractor(barrier),
    )

    with TestClient(app) as setup_client:
        bootstrap(setup_client)
        case_id = create_case(setup_client).json()["case_id"]
        cookie_value = setup_client.cookies.get("scamflow_session")
        assert cookie_value is not None

    def worker():
        with TestClient(app) as client:
            client.cookies.set("scamflow_session", cookie_value)
            return assess(client, case_id, key="same-key")

    with ThreadPoolExecutor(max_workers=2) as executor:
        responses = [
            future.result(timeout=5)
            for future in (
                executor.submit(worker),
                executor.submit(worker),
            )
        ]

    assert all(response.status_code == 200 for response in responses)
    ids = {response.json()["assessment_id"] for response in responses}
    assert len(ids) == 1
    assert sorted(response.json()["idempotent_replay"] for response in responses) == [False, True]

    with app.state.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(Assessment)) == 1
