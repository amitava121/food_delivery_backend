import os

# Always run against a disposable SQLite file — the app's DATABASE_URL
# points at real Postgres; never drop/mutate that.
os.environ["DATABASE_URL"] = "sqlite+aiosqlite:///./test_api.db"

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from app.main import app
from app.db.base import Base

sync_engine = create_engine(
    "sqlite:///./test_api.db", connect_args={"check_same_thread": False}
)
SyncSession = sessionmaker(bind=sync_engine)


@pytest.fixture()
def db_session():
    """Fresh tables per test; direct DB access for setup the API can't do."""
    Base.metadata.drop_all(bind=sync_engine)
    Base.metadata.create_all(bind=sync_engine)
    db = SyncSession()
    try:
        yield db
    finally:
        db.close()


@pytest.fixture()
def client(db_session):
    # `with` runs the app lifespan (creates tables on the async engine)
    with TestClient(app) as c:
        yield c
