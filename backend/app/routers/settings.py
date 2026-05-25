from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Optional
from ..database import SessionLocal
from ..models import AppSetting

router = APIRouter(prefix="/settings", tags=["settings"])

AD_KEYS = ["ad_server", "ad_domain", "ad_port"]

class ADConfig(BaseModel):
    ad_server: str
    ad_domain: str
    ad_port: Optional[int] = 389
    ad_bind_user: Optional[str] = None
    ad_bind_pass: Optional[str] = None

def _get(db, key):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else None

def _set(db, key, value):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    if row:
        row.value = str(value)
    else:
        db.add(AppSetting(key=key, value=str(value)))
    db.commit()

@router.get("/ad")
def get_ad_config():
    db = SessionLocal()
    try:
        return {
            "ad_server": _get(db, "ad_server") or "",
            "ad_domain": _get(db, "ad_domain") or "",
            "ad_port": int(_get(db, "ad_port") or 389),
            "ad_bind_user": _get(db, "ad_bind_user") or "",
            "ad_bind_pass": _get(db, "ad_bind_pass") or "",
        }
    finally:
        db.close()

@router.post("/ad")
def save_ad_config(config: ADConfig):
    db = SessionLocal()
    try:
        _set(db, "ad_server", config.ad_server)
        _set(db, "ad_domain", config.ad_domain)
        _set(db, "ad_port", config.ad_port or 389)
        if config.ad_bind_user is not None:
            _set(db, "ad_bind_user", config.ad_bind_user)
        if config.ad_bind_pass is not None:
            _set(db, "ad_bind_pass", config.ad_bind_pass)
        return {"ok": True}
    finally:
        db.close()

@router.post("/ad/test")
def test_ad_connection():
    db = SessionLocal()
    try:
        server = _get(db, "ad_server")
        domain = _get(db, "ad_domain")
        port = int(_get(db, "ad_port") or 389)
    finally:
        db.close()

    if not server or not domain:
        raise HTTPException(400, "Configura el servidor y dominio primero")

    try:
        from ldap3 import Server, Connection, ALL
        s = Server(server, port=port, get_info=ALL, connect_timeout=5)
        c = Connection(s)
        c.open()
        return {"ok": True, "message": f"Conexión exitosa a {server}:{port}"}
    except Exception as e:
        raise HTTPException(400, f"No se pudo conectar: {str(e)}")