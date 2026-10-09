#!/bin/sh
set -e
# Create extension/tables/indexes (idempotent) and seed demo data only when the DB is empty.
python - <<'PY'
import os, time
from sqlalchemy import select, func
from app.db import init_db, SessionLocal
from app.models import Tenant

for attempt in range(30):
    try:
        init_db()
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
