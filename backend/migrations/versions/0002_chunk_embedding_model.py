"""record which embedding model produced each chunk vector

Revision ID: 0002
Revises: 0001
"""
import sqlalchemy as sa
from alembic import op

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def _has_column() -> bool:
    return any(c["name"] == "embedding_model" for c in sa.inspect(op.get_bind()).get_columns("chunks"))


def upgrade() -> None:
    if _has_column():
        return
    with op.batch_alter_table("chunks") as batch:
        batch.add_column(sa.Column("embedding_model", sa.String(length=120), nullable=True))
    # Every pre-existing vector came from the offline hashing embedder.
    op.execute("UPDATE chunks SET embedding_model = 'hashing-v1' WHERE embedding IS NOT NULL")


def downgrade() -> None:
    with op.batch_alter_table("chunks") as batch:
        batch.drop_column("embedding_model")
