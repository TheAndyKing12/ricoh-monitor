from fastapi import APIRouter, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime, timedelta
from jose import jwt, JWTError
from ldap3 import Server, Connection, ALL, SIMPLE
from ..database import SessionLocal
from ..models import AppSetting, SystemUser

router = APIRouter(prefix="/auth", tags=["auth"])
security = HTTPBearer()

SECRET_KEY = "ricoh-monitor-secret-2024"
ALGORITHM = "HS256"
TOKEN_EXPIRE_HOURS = 8
VALID_TABS = {"dashboard","printers","counters","inventory","tonerControl","printerAssets","config"}

# ── helpers ──────────────────────────────────────────────
def _get_setting(db, key):
    row = db.query(AppSetting).filter(AppSetting.key == key).first()
    return row.value if row else None

def _create_token(data: dict):
    payload = data.copy()
    payload["exp"] = datetime.utcnow() + timedelta(hours=TOKEN_EXPIRE_HOURS)
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)

def verify_token(credentials: HTTPAuthorizationCredentials = Depends(security)):
    try:
        payload = jwt.decode(credentials.credentials, SECRET_KEY, algorithms=[ALGORITHM])
        return payload
    except JWTError:
        raise HTTPException(401, "Token inválido o expirado")

def require_admin(token=Depends(verify_token)):
    if not token.get("is_admin"):
        raise HTTPException(403, "Se requiere rol de administrador")
    return token

# ── login ─────────────────────────────────────────────────
class LoginRequest(BaseModel):
    username: str
    password: str

@router.post("/login")
def login(req: LoginRequest):
    # ── Usuario de emergencia (siempre primero, sin AD) ──
    if req.username == "SuperAdmin" and req.password == "Villalobos1208":
        token = _create_token({
            "sub": "superadmin",
            "display_name": "Super Admin",
            "is_admin": True,
            "allowed_tabs": "dashboard,printers,counters,inventory,tonerControl,printerAssets,config"
        })
        return {
            "access_token": token,
            "display_name": "Super Admin",
            "is_admin": True,
            "allowed_tabs": ["dashboard","printers","counters","inventory","tonerControl","printerAssets","config"]
        }

    db = SessionLocal()
    try:
        ad_server = _get_setting(db, "ad_server")
        ad_domain = _get_setting(db, "ad_domain")
        ad_port   = int(_get_setting(db, "ad_port") or 389)

        if not ad_server or not ad_domain:
            raise HTTPException(503, "Active Directory no configurado")

        # Validar contra AD
        user_dn = f"{ad_domain}\\{req.username}"
        try:
            s = Server(ad_server, port=ad_port, get_info=ALL, connect_timeout=5)
            c = Connection(s, user=f"{req.username}@{ad_domain}", password=req.password, authentication=SIMPLE, auto_bind=True)
            c.unbind()
        except Exception:
            raise HTTPException(401, "Usuario o contraseña incorrectos")

        # Verificar que el admin le dio acceso
        user = db.query(SystemUser).filter(
            SystemUser.username == req.username.lower(),
            SystemUser.is_active == True
        ).first()

        if not user:
            raise HTTPException(403, "No tienes acceso al sistema. Contacta al administrador.")

        token = _create_token({
            "sub": user.username,
            "display_name": user.display_name or user.username,
            "is_admin": user.is_admin,
            "allowed_tabs": user.allowed_tabs or "dashboard"
        })

        return {
            "access_token": token,
            "display_name": user.display_name or user.username,
            "is_admin": user.is_admin,
            "allowed_tabs": (user.allowed_tabs or "dashboard").split(",")
        }
    finally:
        db.close()
class UserCreate(BaseModel):
    username: str
    display_name: Optional[str] = None
    is_admin: bool = False
    allowed_tabs: List[str] = ["dashboard"]

class UserUpdate(BaseModel):
    display_name: Optional[str] = None
    is_admin: Optional[bool] = None
    is_active: Optional[bool] = None
    allowed_tabs: Optional[List[str]] = None

@router.get("/users")
def list_users(token=Depends(require_admin)):
    db = SessionLocal()
    try:
        users = db.query(SystemUser).order_by(SystemUser.username).all()
        return [_user_dict(u) for u in users]
    finally:
        db.close()

@router.post("/users")
def create_user(data: UserCreate, token=Depends(require_admin)):
    db = SessionLocal()
    try:
        exists = db.query(SystemUser).filter(SystemUser.username == data.username.lower()).first()
        if exists:
            raise HTTPException(400, "El usuario ya existe")
        tabs = ",".join([t for t in data.allowed_tabs if t in VALID_TABS]) or "dashboard"
        u = SystemUser(
            username=data.username.lower(),
            display_name=data.display_name or data.username,
            is_admin=data.is_admin,
            allowed_tabs=tabs
        )
        db.add(u)
        db.commit()
        db.refresh(u)
        return _user_dict(u)
    finally:
        db.close()

@router.put("/users/{user_id}")
def update_user(user_id: int, data: UserUpdate, token=Depends(require_admin)):
    db = SessionLocal()
    try:
        u = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not u:
            raise HTTPException(404, "Usuario no encontrado")
        if data.display_name is not None: u.display_name = data.display_name
        if data.is_admin is not None: u.is_admin = data.is_admin
        if data.is_active is not None: u.is_active = data.is_active
        if data.allowed_tabs is not None:
            u.allowed_tabs = ",".join([t for t in data.allowed_tabs if t in VALID_TABS]) or "dashboard"
        db.commit()
        db.refresh(u)
        return _user_dict(u)
    finally:
        db.close()

@router.delete("/users/{user_id}")
def delete_user(user_id: int, token=Depends(require_admin)):
    db = SessionLocal()
    try:
        u = db.query(SystemUser).filter(SystemUser.id == user_id).first()
        if not u:
            raise HTTPException(404, "Usuario no encontrado")
        db.delete(u)
        db.commit()
        return {"ok": True}
    finally:
        db.close()

def _user_dict(u: SystemUser):
    return {
        "id": u.id,
        "username": u.username,
        "display_name": u.display_name,
        "is_active": u.is_active,
        "is_admin": u.is_admin,
        "allowed_tabs": (u.allowed_tabs or "dashboard").split(",")
    }
@router.get("/ad/search")
def search_ad_user(q: str, token=Depends(require_admin)):
    db = SessionLocal()
    try:
        ad_server = _get_setting(db, "ad_server")
        ad_domain = _get_setting(db, "ad_domain")
        ad_port   = int(_get_setting(db, "ad_port") or 389)
        ad_bind_user = _get_setting(db, "ad_bind_user")
        ad_bind_pass = _get_setting(db, "ad_bind_pass")
    finally:
        db.close()

    if not ad_server or not ad_domain:
        raise HTTPException(503, "Active Directory no configurado")

    if len(q) < 2:
        return []

    try:
        from ldap3 import Server, Connection, ALL, SUBTREE, SIMPLE
        s = Server(ad_server, port=ad_port, get_info=ALL, connect_timeout=5)

        # Usar cuenta de servicio si está configurada, sino intentar anónimo
        if ad_bind_user and ad_bind_pass:
            c = Connection(s, user=f"{ad_bind_user}@{ad_domain}", password=ad_bind_pass, authentication=SIMPLE, auto_bind=True)
        else:
            c = Connection(s, auto_bind=True)

        base_dn = "DC=" + ",DC=".join(ad_domain.split("."))
        c.search(
            search_base=base_dn,
            search_filter=f"(&(objectClass=user)(!(userAccountControl:1.2.840.113556.1.4.803:=2))(|(sAMAccountName={q}*)(displayName={q}*)(cn={q}*)))",
            search_scope=SUBTREE,
            attributes=["sAMAccountName", "displayName", "mail"],
            size_limit=10
        )
        results = []
        for entry in c.entries:
            sam = str(entry.sAMAccountName) if entry.sAMAccountName else ""
            display = str(entry.displayName) if entry.displayName else sam
            mail = str(entry.mail) if entry.mail else ""
            if sam and "$" not in sam:
                results.append({"username": sam, "display_name": display, "mail": mail})
        c.unbind()
        return results
    except Exception as e:
        raise HTTPException(400, f"Error buscando en AD: {str(e)}")