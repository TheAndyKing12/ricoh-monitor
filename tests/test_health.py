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
from app import ricoh_mib
from app.routers import printers as printers_router


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
    response = client.get("/inventory/")
    assert response.status_code == 401

    response = client.get("/inventory/", headers=_auth_headers(is_admin=False, allowed_tabs="dashboard"))
    assert response.status_code == 403

    response = client.get("/inventory/", headers=_auth_headers(is_admin=False, allowed_tabs="inventory"))
    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_dashboard_readonly_login_is_limited_to_dashboard():
    response = client.post("/auth/dashboard")

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_admin"] is False
    assert payload["read_only"] is True
    assert payload["allowed_tabs"] == ["dashboard"]

    headers = {"Authorization": f"Bearer {payload['access_token']}"}
    assert client.get("/cache/printer-status", headers=headers).status_code == 200
    assert client.get("/inventory/", headers=headers).status_code == 403
    assert client.get("/auth/users", headers=headers).status_code == 403


def test_printer_identity_fast_path_does_not_use_http(monkeypatch):
    values = {oid: None for oid in printers_router.PRINTER_IDENTITY_OIDS.values()}
    values[printers_router.PRINTER_IDENTITY_OIDS["sys_name"]] = "TEST-PRINTER"
    values[printers_router.PRINTER_IDENTITY_OIDS["hr_descr_1"]] = "RICOH IM C3000"
    values[printers_router.PRINTER_IDENTITY_OIDS["serial"]] = "SERIAL-1"
    monkeypatch.setattr(printers_router, "get_snmp_values", lambda *args, **kwargs: values)
    monkeypatch.setattr(
        printers_router,
        "resolve_hostname_value",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("HTTP hostname lookup should not run")),
    )

    identity = printers_router.get_printer_identity("192.0.2.1", "public")

    assert identity["name"] == "TEST-PRINTER"
    assert identity["serial"] == "SERIAL-1"


def test_counter_normalization_keeps_mono_models_black_and_white():
    values = {
        ricoh_mib.OID["printer_total"]: 1574285,
        ricoh_mib.OID["ricoh_bw_pages"]: 1040667,
        ricoh_mib.OID["ricoh_color_pages"]: 533618,
    }

    reading, is_color = ricoh_mib.normalize_counter_reading(values, model_text="RICOH IM 4000 B/N", db_is_color=True)

    assert is_color is False
    assert reading.total_pages == 1040667
    assert reading.bw_pages == 1040667
    assert reading.color_pages is None


def test_counter_normalization_derives_color_for_color_models_when_safe():
    values = {
        ricoh_mib.OID["printer_total"]: 1000,
        ricoh_mib.OID["ricoh_bw_pages"]: 700,
    }

    reading, is_color = ricoh_mib.normalize_counter_reading(values, model_text="RICOH IM C3000", db_is_color=None)

    assert is_color is True
    assert reading.total_pages == 1000
    assert reading.bw_pages == 700
    assert reading.color_pages == 300
