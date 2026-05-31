import os
from pathlib import Path

from fastapi.testclient import TestClient


TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_ricoh.db"
TEST_DB.parent.mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("APP_SECRET_KEY", "test-secret")

from app.main import app


client = TestClient(app)


def test_health_endpoint_reports_core_sections():
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["app"] == "Ricoh Monitor"
    assert "database" in payload
    assert "scheduler" in payload
    assert "cache" in payload


def test_logs_endpoint_returns_list():
    response = client.get("/logs/?limit=5")

    assert response.status_code == 200
    assert isinstance(response.json(), list)
