import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

# Must be set before app.database is imported anywhere, so the whole app
# (including the startup equipment-seeding code) talks to an isolated
# sqlite file instead of the real ./mes.db used by the running server.
TEST_DB_PATH = ROOT / "tests" / "test_mes.db"
os.environ["MES_DATABASE_URL"] = f"sqlite:///{TEST_DB_PATH}"

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture()
def client():
    """Fresh schema (and re-seeded equipment) for every test."""
    Base.metadata.drop_all(bind=engine)
    Base.metadata.create_all(bind=engine)
    with TestClient(app) as c:
        yield c


def pytest_sessionfinish(session, exitstatus):
    TEST_DB_PATH.unlink(missing_ok=True)
