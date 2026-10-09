"""Start a throwaway local PostgreSQL+pgvector (pgserver wheel) and print its SQLAlchemy URL. Ctrl-C to stop."""
import sys
import tempfile
import time

import pgserver

d = sys.argv[1] if len(sys.argv) > 1 else tempfile.mkdtemp()
srv = pgserver.get_server(d, cleanup_mode="stop")
print(srv.get_uri().replace("postgresql://", "postgresql+psycopg://", 1), flush=True)
while True:
    time.sleep(3600)
