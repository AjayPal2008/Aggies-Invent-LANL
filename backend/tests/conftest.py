"""Each test session gets its own temporary database and copy of the sample data."""
import os
import shutil
import sys
import tempfile
from pathlib import Path

import pytest

BACKEND = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND))

_tmp = Path(tempfile.mkdtemp(prefix="lanl-test-"))
shutil.copytree(BACKEND / "data" / "sample", _tmp / "data")
os.environ["DATABASE_URL"] = f"sqlite:///{_tmp / 'test.db'}"
os.environ["DATA_DIR"] = str(_tmp / "data")
os.environ["ANTHROPIC_API_KEY"] = ""  # tests never call the real AI
os.environ["EMAIL_MODE"] = "preview"
os.environ["UPLOAD_DIR"] = str(_tmp / "uploads")
# Generous limits so the suite never trips them by accident; test_safeguards tightens them on purpose.
os.environ["RATE_LIMIT_PER_MINUTE"] = "100000"
os.environ["RATE_LIMIT_AI_PER_MINUTE"] = "10000"
os.environ["RATE_LIMIT_LOGIN_PER_MINUTE"] = "10000"


@pytest.fixture(scope="session")
def data_dir() -> Path:
    return _tmp / "data"


@pytest.fixture(scope="session")
def client():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:  # startup loads the sample data
        yield c


def _login(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": "demo1234"})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['token']}"}


@pytest.fixture(scope="session")
def hire(client):
    return _login(client, "hire@lanl.gov")


@pytest.fixture(scope="session")
def manager(client):
    return _login(client, "manager@lanl.gov")


@pytest.fixture(scope="session")
def admin(client):
    return _login(client, "admin@lanl.gov")
