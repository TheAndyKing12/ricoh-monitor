import os
from pathlib import Path
from datetime import datetime, timedelta

from fastapi.testclient import TestClient
from jose import jwt


TEST_DB = Path(__file__).resolve().parents[1] / "tmp" / "test_ricoh.db"
TEST_DB.parent.mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{TEST_DB.as_posix()}")
os.environ.setdefault("APP_SECRET_KEY", "test-secret")

from app.main import app


client = TestClient(app)


def _auth_headers(is_admin=True, allowed_tabs="dashboard"):
    token = jwt.encode(
        {
            "sub": "test-user",
            "is_admin": is_admin,
            "allowed_tabs": allowed_tabs,
            "exp": datetime.utcnow() + timedelta(minutes=5),
        },
        os.environ["APP_SECRET_KEY"],
        algorithm="HS256",
    )
    return {"Authorization": f"Bearer {token}"}


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
    assert response.status_code == 401

    response = client.get("/logs/?limit=5", headers=_auth_headers())

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_inventory_requires_matching_tab_permission():
    response = client.get("/logs/?limit=5")
    assert response.status_code == 401

    response = client.get("/inventory/", headers=_auth_headers(is_admin=False, allowed_tabs="dashboard"))
    assert response.status_code == 403

    response = client.get("/inventory/", headers=_auth_headers(is_admin=False, allowed_tabs="inventory"))
    assert response.status_code == 200
    assert isinstance(response.json(), list)
