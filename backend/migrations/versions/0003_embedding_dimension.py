"""resize the pgvector column to EMBEDDING_DIM (e.g. 256 -> 768 for nomic-embed-text)

Vectors from different models/dimensions are not comparable, so existing embeddings are cleared;
run `python -m app.reindex` afterwards to re-embed every chunk with the configured model.
The target width is read from EMBEDDING_DIM. On non-PostgreSQL databases (JSON storage) this is a no-op.

Revision ID: 0003
Revises: 0002
"""
import sqlalchemy as sa
from alembic import op

from app.config import get_settings

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def _current_dim() -> int | None:
    # pgvector stores the dimension in atttypmod
    row = op.get_bind().execute(sa.text(
        "SELECT atttypmod FROM pg_attribute WHERE attrelid = 'chunks'::regclass AND attname = 'embedding'")).first()
    return row[0] if row and row[0] and row[0] > 0 else None


def _resize(dim: int) -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    if _current_dim() == dim:
        return
    op.execute("DROP INDEX IF EXISTS ix_chunks_embedding_hnsw")
    op.execute("UPDATE chunks SET embedding = NULL, embedding_model = NULL")
    op.execute(f"ALTER TABLE chunks ALTER COLUMN embedding TYPE vector({int(dim)})")
    op.execute("CREATE INDEX IF NOT EXISTS ix_chunks_embedding_hnsw ON chunks USING hnsw (embedding vector_cosine_ops)")


def upgrade() -> None:
    _resize(get_settings().embedding_dim)


def downgrade() -> None:
    _resize(256)
