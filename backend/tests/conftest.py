import os
import sys
import tempfile
from pathlib import Path

import pytest

_tmp = Path(tempfile.mkdtemp(prefix="kompas-test-"))
# TEST_DATABASE_URL — прогон на PostgreSQL (в контейнере); по умолчанию — временная SQLite
os.environ["DATABASE_URL"] = os.getenv("TEST_DATABASE_URL") or f"sqlite:///{(_tmp / 'test.db').as_posix()}"
os.environ["MASTER_KEY_FILE"] = str(_tmp / "master.key")
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from fastapi.testclient import TestClient  # noqa: E402

from app import seed  # noqa: E402
from app.main import app  # noqa: E402

PASSWORD = seed.PASSWORD


@pytest.fixture(scope="session")
def client():
    seed.run(reset=True)
    with TestClient(app) as c:
        yield c


@pytest.fixture(scope="session")
def tokens(client):
    out = {}
    for login in ("psychiatrist", "therapist", "duty", "admin", "patient1", "patient3", "patient4", "patient5", "patient6"):
        r = client.post("/api/auth/login", json={"login": login, "password": PASSWORD})
        assert r.status_code == 200, r.text
        out[login] = {"Authorization": f"Bearer {r.json()['token']}"}
    return out


def pid(client, tokens, doctor, code):
    for p in client.get("/api/doctor/patients", headers=tokens[doctor]).json():
        if p["code"] == code:
            return p["id"]
    raise AssertionError(code)
