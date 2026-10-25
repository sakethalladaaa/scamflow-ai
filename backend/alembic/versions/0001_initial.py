"""Initial versioned schema for all ScamFlow persistence models."""

from alembic import op
from backend.scamflow import models  # noqa: F401
from backend.scamflow.database import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    Base.metadata.create_all(op.get_bind())


def downgrade() -> None:
    Base.metadata.drop_all(op.get_bind())
