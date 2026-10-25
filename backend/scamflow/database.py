"""SQLAlchemy database lifecycle helpers for ScamFlow AI."""

from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from .settings import Settings


class Base(DeclarativeBase):
    """Declarative base for ScamFlow AI persistence models."""


@dataclass
class Database:
    """Application-owned database resources."""

    engine: Engine
    session_factory: sessionmaker[Session]

    def session(self) -> Iterator[Session]:
        """Yield one SQLAlchemy session and always close it."""

        with self.session_factory() as session:
            yield session

    def dispose(self) -> None:
        """Release pooled SQLite connections."""

        self.engine.dispose()


def _sqlite_url(path: Path) -> str:
    return f"sqlite+pysqlite:///{path.resolve()}"


def create_database(settings: Settings) -> Database:
    """Create an engine/session factory without creating schema implicitly."""

    database_path = settings.database_path
    database_path.parent.mkdir(parents=True, exist_ok=True)

    engine = create_engine(
        _sqlite_url(database_path),
        connect_args={"check_same_thread": False},
        pool_pre_ping=True,
    )

    @event.listens_for(engine, "connect")
    def configure_sqlite(dbapi_connection: object, _connection_record: object) -> None:
        cursor = dbapi_connection.cursor()  # type: ignore[attr-defined]
        try:
            cursor.execute("PRAGMA foreign_keys=ON")
            cursor.execute(f"PRAGMA busy_timeout={settings.sqlite_busy_timeout_ms}")
            cursor.execute("PRAGMA journal_mode=WAL")
        finally:
            cursor.close()

    return Database(
        engine=engine,
        session_factory=sessionmaker(
            bind=engine,
            class_=Session,
            expire_on_commit=False,
            autoflush=False,
        ),
    )


def initialize_schema(database: Database) -> None:
    """Create the current prototype schema explicitly.

    Phase 2 uses metadata creation only for the initial schema. Future schema
    changes must use explicit migrations rather than deleting existing data.
    """

    # Import models here so metadata registration is explicit and occurs only
    # during application/database initialization, not on module import.
    from . import models as _models  # noqa: F401

    # Keep the Phase 1-3 create-all boundary intact. Later tables are installed
    # only by explicit, recorded additive migrations below.
    migration_managed_tables = {
        "alert_memories",
        "assessment_alerts",
        "review_requests",
        "review_request_idempotency_records",
    }
    Base.metadata.create_all(
        database.engine,
        tables=[
            table
            for table in Base.metadata.sorted_tables
            if table.name not in migration_managed_tables
        ],
    )
    _apply_additive_migrations(database)


def _apply_additive_migrations(database: Database) -> None:
    """Apply idempotent prototype migrations without resetting user data."""

    with database.engine.begin() as connection:
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS schema_migrations (
                    version VARCHAR(64) PRIMARY KEY,
                    applied_at INTEGER NOT NULL
                )
                """
            )
        )
        installed = connection.scalar(
            text("SELECT version FROM schema_migrations WHERE version = :version"),
            {"version": "0001_alert_memory"},
        )
        if installed is not None:
            _apply_review_request_migration(connection)
            return

        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS assessment_alerts (
                    assessment_id VARCHAR(32) PRIMARY KEY
                        REFERENCES assessments(id) ON DELETE CASCADE,
                    visible BOOLEAN NOT NULL,
                    reason VARCHAR(96) NOT NULL,
                    prior_warning_state VARCHAR(64)
                )
                """
            )
        )
        connection.execute(
            text(
                """
                CREATE TABLE IF NOT EXISTS alert_memories (
                    case_id VARCHAR(32) PRIMARY KEY
                        REFERENCES cases(id) ON DELETE CASCADE,
                    owner_id VARCHAR(32) NOT NULL
                        REFERENCES owner_sessions(id) ON DELETE CASCADE,
                    warning_state VARCHAR(64) NOT NULL,
                    material_signature VARCHAR(64) NOT NULL,
                    source_assessment_id VARCHAR(32) NOT NULL
                        REFERENCES assessments(id) ON DELETE CASCADE,
                    source_revision INTEGER NOT NULL,
                    updated_at INTEGER NOT NULL
                )
                """
            )
        )
        connection.execute(
            text(
                "CREATE INDEX IF NOT EXISTS ix_alert_memories_owner_id "
                "ON alert_memories(owner_id)"
            )
        )
        connection.execute(
            text(
                "INSERT INTO schema_migrations(version, applied_at) "
                "VALUES (:version, CAST(strftime('%s','now') AS INTEGER))"
            ),
            {"version": "0001_alert_memory"},
        )
        _apply_review_request_migration(connection)


def _apply_review_request_migration(connection) -> None:
    """Install persisted review requests as an idempotent SQLite migration."""

    installed = connection.scalar(
        text("SELECT version FROM schema_migrations WHERE version = :version"),
        {"version": "0002_review_requests"},
    )
    if installed is not None:
        return

    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS review_requests (
                id VARCHAR(32) PRIMARY KEY,
                case_id VARCHAR(32) NOT NULL REFERENCES cases(id) ON DELETE CASCADE,
                owner_id VARCHAR(32) NOT NULL REFERENCES owner_sessions(id) ON DELETE CASCADE,
                assessment_id VARCHAR(32) NOT NULL REFERENCES assessments(id) ON DELETE CASCADE,
                assessed_revision INTEGER NOT NULL,
                status VARCHAR(16) NOT NULL CHECK (status IN ('open', 'resolved')),
                submitted_at INTEGER NOT NULL,
                resolved_at INTEGER,
                outcome VARCHAR(32),
                reviewer_note TEXT,
                CHECK (
                    (status = 'open' AND resolved_at IS NULL AND outcome IS NULL
                        AND reviewer_note IS NULL)
                    OR
                    (status = 'resolved' AND resolved_at IS NOT NULL AND outcome IN
                        ('follow_up', 'escalated', 'no_action', 'inconclusive'))
                ),
                CHECK (reviewer_note IS NULL OR length(reviewer_note) <= 1000)
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_review_requests_case_id "
            "ON review_requests(case_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_review_requests_owner_id "
            "ON review_requests(owner_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_review_requests_assessment_id "
            "ON review_requests(assessment_id)"
        )
    )
    connection.execute(
        text(
            "CREATE UNIQUE INDEX IF NOT EXISTS uq_review_requests_one_open_case_revision "
            "ON review_requests(case_id, assessed_revision) WHERE status = 'open'"
        )
    )
    connection.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS review_request_idempotency_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                owner_id VARCHAR(32) NOT NULL
                    REFERENCES owner_sessions(id) ON DELETE CASCADE,
                operation_scope VARCHAR(96) NOT NULL,
                request_key VARCHAR(128) NOT NULL,
                request_fingerprint VARCHAR(64) NOT NULL,
                target_case_id VARCHAR(32) REFERENCES cases(id) ON DELETE SET NULL,
                review_request_id VARCHAR(32)
                    REFERENCES review_requests(id) ON DELETE SET NULL,
                result_status_code INTEGER NOT NULL,
                resource_deleted BOOLEAN NOT NULL DEFAULT 0,
                created_at INTEGER NOT NULL,
                CONSTRAINT uq_review_request_idempotency_owner_scope_key
                    UNIQUE (owner_id, operation_scope, request_key)
            )
            """
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_review_request_idempotency_records_owner_id "
            "ON review_request_idempotency_records(owner_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_review_request_idempotency_records_target_case_id "
            "ON review_request_idempotency_records(target_case_id)"
        )
    )
    connection.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_review_request_idempotency_records_review_request_id "
            "ON review_request_idempotency_records(review_request_id)"
        )
    )
    connection.execute(
        text(
            "INSERT INTO schema_migrations(version, applied_at) "
            "VALUES ('0002_review_requests', CAST(strftime('%s','now') AS INTEGER))"
        )
    )
