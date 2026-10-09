"""Alembic environment. The URL comes from app settings (DATABASE_URL), the metadata from the models."""
from __future__ import annotations

from alembic import context

from app import models  # noqa: F401  (register tables)
from app.config import get_settings
from app.db import Base, make_engine

config = context.config
target_metadata = Base.metadata


def _url() -> str:
    # `alembic -x url=...` or a pre-set sqlalchemy.url (used by tests) wins over the environment.
    return context.get_x_argument(as_dictionary=True).get("url") or config.get_main_option("sqlalchemy.url") or get_settings().database_url


def _compare_type(ctx, inspected_column, metadata_column, inspected_type, metadata_type) -> bool | None:
    # Embedding columns are pgvector `vector(N)` on Postgres and JSON elsewhere; their dimension is
    # managed by an explicit migration, so do not let autogenerate try to diff them.
    if type(metadata_type).__name__ == "EmbeddingType":
        return False
    return None


def run_migrations_offline() -> None:
    context.configure(url=_url(), target_metadata=target_metadata, literal_binds=True,
                      compare_type=_compare_type, render_as_batch=True)
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = config.attributes.get("connection")
    if connectable is None:
        engine = make_engine(_url())
        with engine.connect() as connection:
            _run(connection)
        engine.dispose()
    else:
        _run(connectable)


def _run(connection) -> None:
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=_compare_type,
                      render_as_batch=connection.dialect.name == "sqlite")
    with context.begin_transaction():
        context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
