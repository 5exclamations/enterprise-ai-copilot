"""Run the test-suite against a throwaway local PostgreSQL+pgvector (via the pgserver wheel)."""
import subprocess, sys, tempfile, pgserver
with tempfile.TemporaryDirectory() as d:
    srv = pgserver.get_server(d, cleanup_mode="stop")
    uri = srv.get_uri().replace("postgresql://", "postgresql+psycopg://", 1)
    print("pg uri:", uri)
    env = {**__import__("os").environ, "TEST_DATABASE_URL": uri, "DATABASE_URL": uri}
    sys.exit(subprocess.call([sys.executable, "-m", "pytest", "-q", "-p", "no:warnings", "-x"], env=env))
