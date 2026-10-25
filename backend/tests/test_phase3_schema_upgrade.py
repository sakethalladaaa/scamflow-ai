from pathlib import Path

from sqlalchemy import inspect, select, text

from backend.scamflow.api_schemas import CreateCaseRequest
from backend.scamflow.database import Base, create_database, initialize_schema
from backend.scamflow.models import Case
from backend.scamflow.schemas import PaymentContext, ScamEvent
from backend.scamflow.services import authenticate_owner, bootstrap_session, create_case
from backend.scamflow.settings import Environment, Settings


def test_existing_phase2_database_gains_phase3_tables_without_losing_cases(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "upgrade.sqlite3",
    )
    database = create_database(settings)
    now = 1_800_000_000

    try:
        # Simulate the Phase 2 schema by creating only the original four tables.
        original_tables = [
                Base.metadata.tables["accounts"],
            Base.metadata.tables["owner_sessions"],
            Base.metadata.tables["cases"],
            Base.metadata.tables["events"],
            Base.metadata.tables["idempotency_records"],
        ]
        Base.metadata.create_all(database.engine, tables=original_tables)

        session_result = bootstrap_session(
            database,
            settings,
            presented_token=None,
            now=now,
        )
        owner = authenticate_owner(
            database,
            token=session_result.token,
            now=now,
        )
        created = create_case(
            database,
            settings,
            owner_id=owner.id,
            request_key="phase2-create",
            request=CreateCaseRequest(
                consent=True,
                payment_context=PaymentContext(stated_purpose="Verification"),
                events=[
                    ScamEvent(
                        event_id="evt-1",
                        channel="sms",
                        text="Existing Phase 2 evidence",
                        source_order=1,
                    )
                ],
            ),
            now=now,
        )

        initialize_schema(database)

        table_names = set(inspect(database.engine).get_table_names())
        assert {
            "assessments",
            "assessment_evidence",
            "assessment_idempotency_records",
            "assessment_alerts",
            "alert_memories",
            "review_requests",
            "review_request_idempotency_records",
            "schema_migrations",
        }.issubset(table_names)

        with database.session_factory() as session:
            existing_case = session.scalar(select(Case).where(Case.id == created.case_id))
            assert existing_case is not None
            assert existing_case.revision == 1
            assert existing_case.stated_purpose == "Verification"
    finally:
        database.dispose()


def test_existing_phase3_database_applies_review_migration_after_alert_migration(
    tmp_path: Path,
) -> None:
    settings = Settings(
        environment=Environment.TEST,
        database_path=tmp_path / "phase3-to-phase6.sqlite3",
    )
    database = create_database(settings)
    try:
        initialize_schema(database)
        with database.engine.begin() as connection:
            connection.execute(text("DROP TABLE review_request_idempotency_records"))
            connection.execute(text("DROP TABLE review_requests"))
            connection.execute(
                text("DELETE FROM schema_migrations WHERE version = '0002_review_requests'")
            )

        initialize_schema(database)

        table_names = set(inspect(database.engine).get_table_names())
        assert {
            "review_requests",
            "review_request_idempotency_records",
        }.issubset(table_names)
        with database.engine.connect() as connection:
            versions = set(connection.scalars(text("SELECT version FROM schema_migrations")))
        assert "0001_alert_memory" in versions
        assert "0002_review_requests" in versions
    finally:
        database.dispose()
