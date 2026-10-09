import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["LLM_PROVIDER"] = "mock"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from app import auth
from app.auth import Principal
from app.db import get_db, init_db, make_engine
from app.main import create_app
from app.models import User
from app.seed import DEMO_KEYS, seed_database
from app.retrieval.hybrid import HybridRetriever

TEST_DB_URL = os.environ.get("TEST_DATABASE_URL")  # set to a pgvector Postgres to run the suite there


@pytest.fixture()
def engine():
    eng = make_engine(TEST_DB_URL or "sqlite://")
    if TEST_DB_URL:
        from app.db import Base
        Base.metadata.drop_all(eng)
    init_db(eng)
    return eng


@pytest.fixture()
def db(engine):
    Session = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
    with Session() as s:
        seed_database(s)
        yield s


@pytest.fixture()
def principal(db):
    def make(email: str) -> Principal:
        u = db.scalar(select(User).where(User.email == email))
        return Principal(u.id, u.tenant_id, u.role, u.name, u.email)
    return make


@pytest.fixture()
def manager(principal):
    return principal("morgan@helix-supply.example")


@pytest.fixture()
def viewer(principal):
    return principal("vic@helix-supply.example")


@pytest.fixture()
def verdant(principal):
    return principal("vera@verdant-foods.example")


@pytest.fixture()
def client(engine, db):
    auth.reset_limiter()
    app = create_app()
    def override():
        yield db
    app.dependency_overrides[get_db] = override
    with TestClient(app) as c:
        yield c


def hdr(name: str) -> dict:
    return {"X-API-Key": DEMO_KEYS[name]}
