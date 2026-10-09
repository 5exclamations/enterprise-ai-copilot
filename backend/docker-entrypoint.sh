#!/bin/sh
set -e
# Apply Alembic migrations (creates extension/tables/indexes; adopts pre-Alembic databases), then seed demo data only when the DB is empty.
python - <<'PY'
import os, time
from sqlalchemy import select, func
from alembic import command
from alembic.config import Config
from app.db import SessionLocal
from app.models import Tenant

for attempt in range(30):
    try:
        command.upgrade(Config('alembic.ini'), 'head')
        break
    except Exception as exc:  # database still starting
        print(f"waiting for database ({exc.__class__.__name__})...", flush=True)
        time.sleep(2)
else:
    raise SystemExit("database never became available")

if os.environ.get("SEED_ON_START", "true").lower() == "true":
    with SessionLocal() as s:
        if not s.scalar(select(func.count()).select_from(Tenant)):
            from app.seed import seed_database
            seed_database(s)
            print("seeded demo data", flush=True)
PY
exec "$@"
