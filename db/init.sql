-- Runs once on first start of the Postgres container. The app also runs this idempotently.
CREATE EXTENSION IF NOT EXISTS vector;
