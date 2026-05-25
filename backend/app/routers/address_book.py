
import json
import os
import re
import threading
import time
import base64
import traceback
from pathlib import Path
from typing import List

import requests
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session
from app import crud
from app.database import SessionLocal
from app.models import Printer

router = APIRouter(prefix="/printers", tags=["AddressBook"])

STORE_LOCK = threading.Lock()
STORE_PATH = Path(__file__).resolve().parents[2] / "data" / "address_book_store.json"
DEFAULT_STORAGE_MODE = "ricoh-real"
SUPPORTED_STORAGE_MODES = {"local-safe", "ricoh-real"}
RICOH_HTTP_TIMEOUT = 8
RAW_DUMP_PATH = Path(__file__).resolve().parents[2] / "data" / "address_book_last_raw_response.html"
ADRSLIST_DUMP_PATH = Path(__file__).resolve().parents[2] / "data" / "address_book_last_page.html"
ADDRESS_BOOK_BROWSER_LOGIN_ENABLED = (os.getenv("ADDRESS_BOOK_BROWSER_LOGIN_ENABLED", "0") or "0").strip().lower() in {"1", "true", "yes", "on"}
RICOH_SESSION_LOCKS: dict[str, threading.Lock] = {}
RICOH_SESSION_LOCKS_GUARD = threading.Lock()

RICOH_SESSION_POOL: dict[str, tuple[requests.Session, float]] = {}
RICOH_SESSION_POOL_LOCK = threading.Lock()
RICOH_SESSION_TIMEOUT = 300  # 5 minutos


def _cleanup_expired_sessions():
    """Remove expired sessions from pool (internal, no lock needed - caller must hold lock)"""
    import time
    now = time.time()
    expired = [ip for ip, (_, ts) in RICOH_SESSION_POOL.items() if now - ts > RICOH_SESSION_TIMEOUT]
    for ip in expired:
        session, _ = RICOH_SESSION_POOL.pop(ip)
        try:
            _ricoh_logout_address_book(session, ip)
        except:
            pass


def _get_or_create_ricoh_session(printer_ip: str, admin: str, password: str, force_new: bool = False) -> requests.Session:
    """Get existing session from pool or create new one with login"""
    import time
    
    with RICOH_SESSION_POOL_LOCK:
        _cleanup_expired_sessions()
        
        if not force_new and printer_ip in RICOH_SESSION_POOL:
            session, _ = RICOH_SESSION_POOL[printer_ip]
            # Update timestamp
            RICOH_SESSION_POOL[printer_ip] = (session, time.time())
            return session
        
        # Create new session
        session = _ricoh_build_session(printer_ip)
        
        try:
            success = _ricoh_login_address_book(session, printer_ip, admin, password)
        except HTTPException as e:
            # Re-lanzar HTTPException con diagnósticos
            raise e
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Login error: {type(e).__name__}: {str(e)[:200]}")
        
        if not success:
            raise HTTPException(status_code=401, detail="Failed to authenticate with Ricoh printer")
        
        RICOH_SESSION_POOL[printer_ip] = (session, time.time())
        return session


def _close_ricoh_session(printer_ip: str):
    """Close and remove session from pool"""
    with RICOH_SESSION_POOL_LOCK:
        if printer_ip in RICOH_SESSION_POOL:
            session, _ = RICOH_SESSION_POOL.pop(printer_ip)
            try:
                _ricoh_logout_address_book(session, printer_ip)
            except:
                pass


def _get_ricoh_session_lock(printer_ip: str) -> threading.Lock:
    """Get or create a lock for a specific printer IP"""
    with RICOH_SESSION_LOCKS_GUARD:
        if printer_ip not in RICOH_SESSION_LOCKS:
            RICOH_SESSION_LOCKS[printer_ip] = threading.Lock()
        return RICOH_SESSION_LOCKS[printer_ip]


def _dump_ricoh_address_scripts(session: requests.Session, printer_ip: str, page_html: str):
    script_paths = re.findall(r'<script[^>]+src=["\']([^"\']+\.xjs)["\']', page_html or "", flags=re.IGNORECASE)
    if not script_paths:
        return
    out_dir = ADRSLIST_DUMP_PATH.parent
    out_dir.mkdir(parents=True, exist_ok=True)
    for src in sorted(set(script_paths)):
        src_path = src.strip()
        if not src_path:
            continue
        if src_path.startswith("http://") or src_path.startswith("https://"):
            url = src_path
        elif src_path.startswith("/"):
            url = f"http://{printer_ip}{src_path}"
        else:
            url = f"http://{printer_ip}/web/entry/es/address/{src_path}"
        try:
            resp = session.get(url, timeout=RICOH_HTTP_TIMEOUT)
            safe_name = src_path.replace("/", "_").replace("\\", "_")
            (out_dir / f"address_book_{safe_name}").write_text(resp.text or "", encoding="utf-8", errors="ignore")
        except Exception:
            continue


class AddressBookEntryBase(BaseModel):
    name: str
    key_display: str | None = None
    freq: bool = True
    title1: str | None = None
    title2: str | None = None
    title3: str | None = None
    user_code: str | None = None
    email_address: str | None = None
    folder: str | None = None
    status: str | None = "Activo"


class AddressBookEntryCreate(AddressBookEntryBase):
    registration_no: str | None = None


class AddressBookEntryUpdate(AddressBookEntryBase):
    name: str | None = None


class AddressBookEntry(AddressBookEntryBase):
    registration_no: str


class AddressBookListResponse(BaseModel):
    printer_id: int
    printer_ip: str
    storage_mode: str
    entries: list[AddressBookEntry]


class AddressBookAuthRequest(BaseModel):
    admin: str
    password: str


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_store_dir():
    STORE_PATH.parent.mkdir(parents=True, exist_ok=True)


def _load_store() -> dict:
    _ensure_store_dir()
    if not STORE_PATH.exists():
        return {}
    try:
        return json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _save_store(data: dict):
    _ensure_store_dir()
    STORE_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def _get_printer_or_404(db: Session, printer_id: int):
    printer = crud.get_printer_by_id(db, printer_id)
    if not printer:
        raise HTTPException(status_code=404, detail="Printer not found")
    return printer


def _sort_entries(entries: list[dict]) -> list[dict]:
    def is_zero_registration(value) -> bool:
        text = str(value or "").strip()
        return text.isdigit() and int(text) == 0

    cleaned = [item for item in (entries or []) if not is_zero_registration(item.get("registration_no"))]
    return sorted(cleaned, key=lambda item: int(str(item.get("registration_no") or "0")))


def _next_registration_no(entries: list[dict]) -> str:
    max_value = 0
    for entry in entries:
        try:
            max_value = max(max_value, int(str(entry.get("registration_no") or "0")))
        except Exception:
            continue
    return str(max_value + 1).zfill(5)


def _get_storage_mode(override_mode: str | None = None) -> str:
    if override_mode:
        mode = override_mode.strip().lower()
        if mode in SUPPORTED_STORAGE_MODES:
            return mode
    mode = (os.getenv("ADDRESS_BOOK_STORAGE_MODE", DEFAULT_STORAGE_MODE) or DEFAULT_STORAGE_MODE).strip().lower()
    return mode if mode in SUPPORTED_STORAGE_MODES else DEFAULT_STORAGE_MODE


def _get_local_entries(printer_id: int) -> list[dict]:
    with STORE_LOCK:
        store = _load_store()
        return _sort_entries(store.get(str(printer_id), []))


def _create_local_entry(printer_id: int, payload: AddressBookEntryCreate) -> dict:
    with STORE_LOCK:
        store = _load_store()
        entries = store.setdefault(str(printer_id), [])
        registration_no = (payload.registration_no or "").strip() or _next_registration_no(entries)
        if any(str(item.get("registration_no")) == registration_no for item in entries):
            raise HTTPException(status_code=400, detail="Registration number already exists")
        entry = payload.dict()
        entry["registration_no"] = registration_no
        entries.append(entry)
        store[str(printer_id)] = _sort_entries(entries)
        _save_store(store)
    return entry


def _update_local_entry(printer_id: int, registration_no: str, payload: AddressBookEntryUpdate) -> dict:
    with STORE_LOCK:
        store = _load_store()
        entries = store.get(str(printer_id), [])
        target = next((item for item in entries if str(item.get("registration_no")) == registration_no), None)
        if not target:
            raise HTTPException(status_code=404, detail="Address book entry not found")
        for key, value in payload.dict(exclude_unset=True).items():
            target[key] = value
        store[str(printer_id)] = _sort_entries(entries)
        _save_store(store)
    return target


def _delete_local_entry(printer_id: int, registration_no: str):
    with STORE_LOCK:
        store = _load_store()
        entries = store.get(str(printer_id), [])
        new_entries = [item for item in entries if str(item.get("registration_no")) != registration_no]
        if len(new_entries) == len(entries):
            raise HTTPException(status_code=404, detail="Address book entry not found")
        store[str(printer_id)] = _sort_entries(new_entries)
        _save_store(store)


def _ricoh_credentials(admin: str | None = None, password: str | None = None) -> tuple[str, str]:
    user = (admin or os.getenv("RICOH_ADDRESSBOOK_USER", "admin") or "admin").strip()
    secret = password if password is not None else (os.getenv("RICOH_ADDRESSBOOK_PASSWORD", "") or "")
    return user, secret


def _ricoh_build_session(printer_ip: str) -> requests.Session:
    session = requests.Session()
    session.headers.update({
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    })
    # Ricoh requiere esta cookie o devuelve MSG_COOKIEOFF redirect.
    # Usar session.cookies.set() para que se fusione con las cookies
    # que Ricoh asigna (risessionid, wimsesid) en las siguientes requests.
    session.cookies.set("cookieOnOffChecker", "on")
    return session


def _ricoh_login_address_book(session: requests.Session, printer_ip: str, admin: str | None = None, password: str | None = None):
    def _has_max_users_error(text: str) -> bool:
        t = (text or "").lower()
        return (
            "número de usuarios que accede al servidor supera el límite máximo permitido" in t
            or "numero de usuarios que accede al servidor supera el limite maximo permitido" in t
        )

    def _is_auth_redirect_page(text: str) -> bool:
        t = (text or "").lower()
        return "authform.cgi" in t and ("document.form1.submit" in t or "<form name='form1'" in t or "<form name=\"form1\"" in t)

    user, secret = _ricoh_credentials(admin, password)
    candidates = [
        {
            "auth_url": f"http://{printer_ip}/web/guest/es/websys/webArch/authForm.cgi?open=address/adrsList.cgi",
            "login_url": f"http://{printer_ip}/web/guest/es/websys/webArch/login.cgi",
            "page_url": f"http://{printer_ip}/web/entry/es/address/adrsList.cgi",
        },
        {
            "auth_url": f"http://{printer_ip}/web/guest/websys/webArch/authForm.cgi?open=address/adrsList.cgi",
            "login_url": f"http://{printer_ip}/web/guest/websys/webArch/login.cgi",
            "page_url": f"http://{printer_ip}/web/entry/address/adrsList.cgi",
        },
    ]

    diagnostics: list[str] = []
    auth_form_available = False
    for idx, c in enumerate(candidates, start=1):
        # --- GET auth form para obtener wimToken ---
        try:
            auth = session.get(c["auth_url"], timeout=RICOH_HTTP_TIMEOUT)
            diagnostics.append(f"c{idx}:auth={auth.status_code}")
        except Exception as ex:
            diagnostics.append(f"c{idx}:auth_exc={type(ex).__name__}")
            continue
        if _has_max_users_error(auth.text or ""):
            raise HTTPException(status_code=503, detail="Ricoh ocupada: demasiadas sesiones web activas. Cierre sesiones abiertas y reintente.")
        if auth.status_code != 200:
            continue

        auth_form_available = True
        token_match = re.search(r'name=["\']wimToken["\'][^>]*value=["\']([^"\']*)["\']', auth.text or "", re.IGNORECASE)
        token = token_match.group(1) if token_match else ""

        hidden_inputs: dict[str, str] = {}
        for input_match in re.finditer(r"<input[^>]*>", auth.text or "", re.IGNORECASE):
            tag = input_match.group(0)
            name_match = re.search(r'name=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not name_match:
                continue
            value_match = re.search(r'value=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            hidden_inputs[name_match.group(1)] = value_match.group(1) if value_match else ""

        # --- Construir payload exactamente como encrypt() de Ricoh ---
        user_b64 = base64.b64encode(user.encode("utf-8")).decode("ascii")
        pass_b64 = base64.b64encode(secret.encode("utf-8")).decode("ascii")

        payload = {
            "wimToken": token or hidden_inputs.get("wimToken", ""),
            "userid": user_b64,
            "password": pass_b64,
            "userid_work": "",
            "password_work": "",
            "open": hidden_inputs.get("open", "address/adrsList.cgi"),
        }

       # REEMPLAZAR la sección del POST login (líneas ~356-375):

        # --- POST login ---
        try:
            # Permitir redirects automáticos
            login_resp = session.post(c["login_url"], data=payload, timeout=RICOH_HTTP_TIMEOUT, allow_redirects=True)
            diagnostics.append(f"c{idx}:login={login_resp.status_code}")
        except Exception as ex:
            diagnostics.append(f"c{idx}:login_exc={type(ex).__name__}")
            continue

        # --- Verificar si login fue exitoso (cambio en wimsesid cookie) ---
        wimsesid_after = session.cookies.get("wimsesid", "")
        diagnostics.append(f"c{idx}:wimsesid={wimsesid_after}")
        
        if wimsesid_after and wimsesid_after != "0" and wimsesid_after != "--":
            diagnostics.append(f"c{idx}:wimsesid_ok")
            return True

        # --- Fallback: intentar acceder a la página de usuarios para forzar establecimiento de cookie ---
        try:
            page_check = session.get(c["page_url"], timeout=RICOH_HTTP_TIMEOUT, allow_redirects=True)
            wimsesid_after = session.cookies.get("wimsesid", "")
            diagnostics.append(f"c{idx}:page_check={page_check.status_code}:wimsesid={wimsesid_after}")
            
            if wimsesid_after and wimsesid_after != "0" and wimsesid_after != "--":
                diagnostics.append(f"c{idx}:wimsesid_ok_after_page")
                return True
        except Exception as ex:
            diagnostics.append(f"c{idx}:page_check_exc={type(ex).__name__}")

        diagnostics.append(f"c{idx}:login_failed:wimsesid={wimsesid_after}")

    # Si ningún candidato funcionó, incluir diagnósticos en el error
    diag_text = " | ".join(diagnostics[-24:]) if diagnostics else "sin diagnóstico"
    print(f"[ADDRESS_BOOK] Login failed for {printer_ip}. Diagnostics: {diag_text}")
    
    if not auth_form_available:
        raise HTTPException(status_code=502, detail=f"Ricoh auth form not available. Diagnóstico: {diag_text}")
    
    raise HTTPException(status_code=401, detail=f"Credenciales inválidas para la libreta de direcciones. Diagnóstico: {diag_text}")


def _ricoh_logout_address_book(session: requests.Session, printer_ip: str):
    for url in (
        f"http://{printer_ip}/web/entry/es/websys/webArch/logout.cgi",
        f"http://{printer_ip}/web/guest/es/websys/webArch/logout.cgi",
        f"http://{printer_ip}/web/entry/es/address/logout.cgi",
    ):
        try:
            session.get(url, timeout=RICOH_HTTP_TIMEOUT)
        except Exception:
            pass


@router.post("/{printer_id}/address-book/auth")
def validate_address_book_auth(printer_id: int, payload: AddressBookAuthRequest, db: Session = Depends(get_db)):
    printer = _get_printer_or_404(db, printer_id)
    lock = _get_ricoh_session_lock(printer.ip)
    with lock:
        try:
            # Forzar nueva sesión en auth (cierra la anterior si existe)
            session = _get_or_create_ricoh_session(printer.ip, payload.admin, payload.password, force_new=True)
            entries = _ricoh_load_entries_with_session(session, printer.ip, dump=False, admin=payload.admin, password=payload.password)
            
            # Asegurar que entries siempre sea una lista
            if entries is None:
                entries = []
            
            return {
                "valid": True,
                "printer_id": printer.id,
                "printer_ip": printer.ip,
                "storage_mode": "ricoh-real",
                "entries_count": len(entries),
                "entries": entries,
            }
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(status_code=502, detail=f"Error interno en auth Ricoh: {type(ex).__name__}: {str(ex)[:180]}")


@router.post("/{printer_id}/address-book/debug-login")
def debug_address_book_login(printer_id: int, payload: AddressBookAuthRequest, db: Session = Depends(get_db)):
    """Endpoint temporal de diagnóstico — captura HTML real de la Ricoh."""
    import traceback
    try:
        printer = _get_printer_or_404(db, printer_id)
        user, secret = _ricoh_credentials(payload.admin, payload.password)
        session = _ricoh_build_session(printer.ip)
        result = {"printer_ip": printer.ip, "user": user, "steps": []}

        def _safe_cookies(s):
            try:
                return {c.name: c.value for c in s.cookies}
            except Exception:
                return "error_reading_cookies"

        auth_url = f"http://{printer.ip}/web/guest/es/websys/webArch/authForm.cgi?open=address/adrsList.cgi"
        login_url = f"http://{printer.ip}/web/guest/es/websys/webArch/login.cgi"
        page_url = f"http://{printer.ip}/web/entry/es/address/adrsList.cgi"

        # Step 1: GET auth form
        try:
            auth_resp = session.get(auth_url, timeout=RICOH_HTTP_TIMEOUT)
            result["steps"].append({
                "step": "1_auth_form",
                "status": auth_resp.status_code,
                "url": auth_url,
                "html_length": len(auth_resp.text or ""),
                "html_preview": (auth_resp.text or "")[:2000],
                "cookies": _safe_cookies(session),
            })
        except Exception as ex:
            result["steps"].append({"step": "1_auth_form", "error": f"{type(ex).__name__}: {ex}"})
            return result

        token_match = re.search(r'name=["\']wimToken["\'][^>]*value=["\']([^"\']*)["\']', auth_resp.text or "", re.IGNORECASE)
        token = token_match.group(1) if token_match else ""

        hidden_inputs = {}
        for input_match in re.finditer(r"<input[^>]*>", auth_resp.text or "", re.IGNORECASE):
            tag = input_match.group(0)
            name_match = re.search(r'name=["\']([^"\']+)["\']', tag, re.IGNORECASE)
            if not name_match:
                continue
            value_match = re.search(r'value=["\']([^"\']*)["\']', tag, re.IGNORECASE)
            hidden_inputs[name_match.group(1)] = value_match.group(1) if value_match else ""

        user_b64 = base64.b64encode(user.encode("utf-8")).decode("ascii")
        pass_b64 = base64.b64encode(secret.encode("utf-8")).decode("ascii")

        payload_data = {
            "wimToken": token or hidden_inputs.get("wimToken", ""),
            "userid": user_b64,
            "password": pass_b64,
            "userid_work": "",
            "password_work": "",
            "open": hidden_inputs.get("open", "address/adrsList.cgi"),
        }

        # Step 2: POST login
        try:
            login_resp = session.post(login_url, data=payload_data, timeout=RICOH_HTTP_TIMEOUT)
            history_info = []
            try:
                history_info = [{"status": r.status_code, "url": str(r.url)} for r in login_resp.history]
            except Exception:
                history_info = ["error_reading_history"]
            result["steps"].append({
                "step": "2_login_post",
                "status": login_resp.status_code,
                "url": login_url,
                "html_length": len(login_resp.text or ""),
                "html_preview": (login_resp.text or "")[:2000],
                "cookies": _safe_cookies(session),
                "history": history_info,
            })
        except Exception as ex:
            result["steps"].append({"step": "2_login_post", "error": f"{type(ex).__name__}: {ex}"})
            return result

        # Step 3: GET address list page
        try:
            page_resp = session.get(page_url, timeout=RICOH_HTTP_TIMEOUT)
            result["steps"].append({
                "step": "3_page_after_login",
                "status": page_resp.status_code,
                "url": page_url,
                "html_length": len(page_resp.text or ""),
                "html_preview": (page_resp.text or "")[:2000],
                "cookies": _safe_cookies(session),
            })
        except Exception as ex:
            result["steps"].append({"step": "3_page_after_login", "error": f"{type(ex).__name__}: {ex}"})

        try:
            _ricoh_logout_address_book(session, printer.ip)
        except Exception:
            pass

        return result
    except Exception as ex:
        return {"fatal_error": f"{type(ex).__name__}: {ex}", "traceback": traceback.format_exc()}


@router.post("/{printer_id}/address-book/session/close")
def close_address_book_session(printer_id: int, db: Session = Depends(get_db)):
    """Cierra la sesión activa de la libreta de direcciones."""
    printer = _get_printer_or_404(db, printer_id)
    _close_ricoh_session(printer.ip)
    return {"closed": True, "printer_id": printer.id, "printer_ip": printer.ip}


@router.post("/{printer_id}/address-book/logout")
def logout_address_book_session(printer_id: int, admin: str | None = Query(default=None), password: str | None = Query(default=None), db: Session = Depends(get_db)):
    printer = _get_printer_or_404(db, printer_id)
    lock = _get_ricoh_session_lock(printer.ip)
    with lock:
        session = _ricoh_build_session(printer.ip)
        _ricoh_logout_address_book(session, printer.ip)
    return {"logged_out": True, "printer_id": printer.id, "printer_ip": printer.ip}


@router.get("/{printer_id}/address-book/test-login")
def test_login_diagnostics(printer_id: int, admin: str = "admin", password: str = "", db: Session = Depends(get_db)):
    """Test login and return detailed diagnostics"""
    printer = _get_printer_or_404(db, printer_id)
    session = _ricoh_build_session(printer.ip)
    
    # Test auth form
    auth_url = f"http://{printer.ip}/web/guest/es/websys/webArch/authForm.cgi?open=address/adrsList.cgi"
    try:
        auth_resp = session.get(auth_url, timeout=RICOH_HTTP_TIMEOUT)
        auth_status = auth_resp.status_code
        auth_cookies = {c.name: c.value for c in session.cookies}
        has_wimtoken = "wimToken" in auth_resp.text
    except Exception as e:
        return {"error": f"Auth form failed: {e}"}
    
    # Extract wimToken
    token_match = re.search(r'name=["\']wimToken["\'][^>]*value=["\']([^"\']*)["\']', auth_resp.text or "", re.IGNORECASE)
    token = token_match.group(1) if token_match else ""
    
    # Build login payload
    user_b64 = base64.b64encode(admin.encode("utf-8")).decode("ascii")
    pass_b64 = base64.b64encode(password.encode("utf-8")).decode("ascii")
    
    payload = {
        "wimToken": token,
        "userid": user_b64,
        "password": pass_b64,
        "userid_work": "",
        "password_work": "",
        "open": "address/adrsList.cgi",
    }
    
    # Test login POST
    login_url = f"http://{printer.ip}/web/guest/es/websys/webArch/login.cgi"
    try:
        login_resp = session.post(login_url, data=payload, timeout=RICOH_HTTP_TIMEOUT)
        login_status = login_resp.status_code
        login_cookies = {c.name: c.value for c in session.cookies}
        wimsesid = session.cookies.get("wimsesid", "")
    except Exception as e:
        return {"error": f"Login POST failed: {e}"}
    
    return {
        "printer_ip": printer.ip,
        "auth_form": {
            "status": auth_status,
            "cookies": auth_cookies,
            "has_wimtoken": has_wimtoken,
            "wimtoken_value": token[:20] + "..." if len(token) > 20 else token,
        },
        "login_post": {
            "status": login_status,
            "cookies": login_cookies,
            "wimsesid": wimsesid,
            "response_preview": login_resp.text[:500] if login_resp.text else "empty",
        },
        "credentials": {
            "admin": admin,
            "password_length": len(password),
            "user_b64": user_b64,
            "pass_b64": pass_b64,
        }
    }


@router.get("/{printer_id}/address-book", response_model=AddressBookListResponse)
def list_address_book(printer_id: int, storage_mode: str | None = Query(default=None), admin: str | None = Query(default=None), password: str | None = Query(default=None), db: Session = Depends(get_db)):
    printer = _get_printer_or_404(db, printer_id)
    storage_mode = _get_storage_mode(storage_mode)
    if storage_mode == "ricoh-real":
        lock = _get_ricoh_session_lock(printer.ip)
        with lock:
            session = _ricoh_build_session(printer.ip)
            try:
                _ricoh_login_address_book(session, printer.ip, admin, password)
                entries = _ricoh_load_entries_with_session(session, printer.ip, dump=False, admin=admin, password=password)
                return {
                    "printer_id": printer.id,
                    "printer_ip": printer.ip,
                    "storage_mode": "ricoh-real",
                    "entries": entries or [],
                }
            except HTTPException:
                raise
            except Exception as ex:
                raise HTTPException(status_code=502, detail=f"Ricoh address book error: {type(ex).__name__}: {str(ex)[:180]}")
            finally:
                try:
                    _ricoh_logout_address_book(session, printer.ip)
                except Exception:
                    pass
    else:
        entries = _get_local_entries(printer.id)
        return {
            "printer_id": printer.id,
            "printer_ip": printer.ip,
            "storage_mode": "local-safe",
            "entries": entries,
        }


def _clear_local_entries(printer_id: int):
    with STORE_LOCK:
        store = _load_store()
        store[str(printer_id)] = []
        _save_store(store)


def _ricoh_extract_wim_token(html: str) -> str:
    token_match = re.search(r'name=["\']wimToken["\'][^>]*value=["\']([^"\']*)["\']', html or "", re.IGNORECASE)
    return token_match.group(1) if token_match else ""


def _ricoh_load_entries_with_session(session: requests.Session, printer_ip: str, dump: bool = False, admin: str | None = None, password: str | None = None) -> list[dict]:
    def _has_max_users_error(text: str) -> bool:
        t = (text or "").lower()
        return (
            "número de usuarios que accede al servidor supera el límite máximo permitido" in t
            or "numero de usuarios que accede al servidor supera el limite maximo permitido" in t
        )

    def _is_auth_redirect(text: str) -> bool:
        t = (text or "").lower()
        return "authform.cgi" in t and "document.form1.submit" in t

    diagnostics: list[str] = []
    saw_auth_redirect = False

    list_page_urls = (
        f"http://{printer_ip}/web/entry/es/address/adrsList.cgi",
        f"http://{printer_ip}/web/entry/address/adrsList.cgi",
    )

    list_page_resp = None
    list_page_url = ""
    for idx, url in enumerate(list_page_urls, start=1):
        try:
            resp = session.get(url, timeout=RICOH_HTTP_TIMEOUT)
            diagnostics.append(f"list{idx}:get={resp.status_code}")
        except Exception as ex:
            diagnostics.append(f"list{idx}:exc={type(ex).__name__}")
            continue
        if _has_max_users_error(resp.text or ""):
            _ricoh_logout_address_book(session, printer_ip)
            _ricoh_login_address_book(session, printer_ip, admin, password)
            resp = session.get(url, timeout=RICOH_HTTP_TIMEOUT)
            diagnostics.append(f"list{idx}:retry={resp.status_code}")
            if _has_max_users_error(resp.text or ""):
                raise HTTPException(
                    status_code=503,
                    detail="Ricoh ocupada: demasiadas sesiones web activas. Cierre sesiones abiertas y reintente.",
                )
        if resp.status_code == 200:
            list_page_resp = resp
            list_page_url = url
            break

    if list_page_resp is None:
        raise HTTPException(status_code=502, detail=f"Ricoh address-book page not available ({' | '.join(diagnostics[-8:])})")

    if _is_auth_redirect(list_page_resp.text or ""):
        saw_auth_redirect = True
        _ricoh_login_address_book(session, printer_ip, admin, password)
        list_page_resp = session.get(list_page_url, timeout=RICOH_HTTP_TIMEOUT)
        diagnostics.append(f"list:relogin={list_page_resp.status_code}")
        if _is_auth_redirect(list_page_resp.text or ""):
            browser_entries = _ricoh_load_entries_with_browser(printer_ip, admin, password, diagnostics)
            if browser_entries is not None:
                return _sort_entries(browser_entries)
            raise HTTPException(status_code=401, detail=f"Credenciales inválidas para la libreta de direcciones ({' | '.join(diagnostics[-12:])})")

    if dump:
        ADRSLIST_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
        ADRSLIST_DUMP_PATH.write_text(list_page_resp.text or "", encoding="utf-8", errors="ignore")
        _dump_ricoh_address_scripts(session, printer_ip, list_page_resp.text or "")

    pre_entries = _ricoh_parse_entries(list_page_resp.text or "")
    if not pre_entries:
        pre_entries = _ricoh_parse_entries_from_html(list_page_resp.text or "")
    if pre_entries:
        return _sort_entries(pre_entries)

    endpoint_candidates = (
        f"http://{printer_ip}/web/entry/es/address/adrsListLoadEntry.cgi",
        f"http://{printer_ip}/web/entry/address/adrsListLoadEntry.cgi",
    )
    param_variants = (
        {"_": str(int(time.time() * 1000)), "listCountIn": "50", "getCountIn": "1"},
        {"_": str(int(time.time() * 1000)), "listCountIn": "100", "getCountIn": "1"},
        {"_": str(int(time.time() * 1000)), "listCount": "50", "getCount": "1"},
        {"_": str(int(time.time() * 1000)), "start": "0", "count": "100"},
        {},
    )

    merged: dict[str, dict] = {}
    raw_dump_written = False

    for ep_idx, endpoint in enumerate(endpoint_candidates, start=1):
        headers = {
            "Accept": "text/plain, */*",
            "X-Requested-With": "XMLHttpRequest",
            "Referer": list_page_url,
        }
        for pv_idx, params in enumerate(param_variants, start=1):
            try:
                api_resp = session.get(endpoint, params=params, headers=headers, timeout=RICOH_HTTP_TIMEOUT)
                diagnostics.append(f"ep{ep_idx}:p{pv_idx}={api_resp.status_code}")
            except Exception as ex:
                diagnostics.append(f"ep{ep_idx}:p{pv_idx}:exc={type(ex).__name__}")
                continue

            if api_resp.status_code != 200:
                continue

            raw_text = api_resp.text or ""
            if not raw_dump_written and dump and raw_text.strip():
                RAW_DUMP_PATH.parent.mkdir(parents=True, exist_ok=True)
                RAW_DUMP_PATH.write_text(raw_text, encoding="utf-8", errors="ignore")
                raw_dump_written = True

            parsed = _ricoh_parse_entries(raw_text)
            for entry in parsed:
                reg = str(entry.get("registration_no") or "").strip().zfill(5)
                if reg:
                    merged[reg] = entry

    if merged:
        return _sort_entries(list(merged.values()))

    # Último intento: revisar scripts inline de la página de lista.
    for script_body in re.findall(r"<script[^>]*>(.*?)</script>", list_page_resp.text or "", flags=re.IGNORECASE | re.DOTALL):
        parsed = _ricoh_parse_entries(script_body or "")
        for entry in parsed:
            reg = str(entry.get("registration_no") or "").strip().zfill(5)
            if reg:
                merged[reg] = entry

    if merged:
        return _sort_entries(list(merged.values()))

    if saw_auth_redirect:
        browser_entries = _ricoh_load_entries_with_browser(printer_ip, admin, password, diagnostics)
        if browser_entries is not None:
            return _sort_entries(browser_entries)
        raise HTTPException(status_code=401, detail=f"Credenciales inválidas para la libreta de direcciones ({' | '.join(diagnostics[-16:])})")

    return []


def _ricoh_set_user(session: requests.Session, printer_ip: str, entry: dict, mode: str):
    reg = str(entry.get("registration_no") or "").strip().zfill(5)
    name = str(entry.get("name") or "").strip()
    if not _is_plausible_reg(reg) or not name:
        raise HTTPException(status_code=400, detail="Invalid staged entry")

    list_page = session.get(f"http://{printer_ip}/web/entry/es/address/adrsList.cgi", timeout=RICOH_HTTP_TIMEOUT)
    token = _ricoh_extract_wim_token(list_page.text)
    if not token:
        raise HTTPException(status_code=502, detail="Ricoh wimToken not found")

    get_payload = {
        "mode": mode,
        "outputSpecifyModeIn": "PROGRAMMED" if mode == "MODUSER" else "DEFAULT",
        "entryIndexIn": reg if mode == "MODUSER" else "",
        "wimToken": token,
    }
    session.post(f"http://{printer_ip}/web/entry/es/address/adrsGetUser.cgi", data=get_payload, timeout=RICOH_HTTP_TIMEOUT)

    key_display = str(entry.get("key_display") or name).strip() or name
    email = str(entry.get("email_address") or "").strip()
    user_code = str(entry.get("user_code") or "").strip()
    folder = str(entry.get("folder") or "").strip()

    post_data = [
        ("inputSpecifyModeIn", "WRITE"),
        ("outputSpecifyModeIn", "PROGRAMMED"),
        ("entryIndexIn", reg),
        ("wimToken", token),
        ("name", name),
        ("keyDisplay", key_display),
        ("freq", "on" if entry.get("freq") else ""),
        ("title1", entry.get("title1") or ""),
        ("title2", entry.get("title2") or ""),
        ("title3", entry.get("title3") or ""),
        ("email", email),
        ("userCode", user_code),
        ("remoteFolder", folder),
        ("protection", ""),
    ]

    set_resp = session.post(f"http://{printer_ip}/web/entry/es/address/adrsSetUser.cgi", data=post_data, timeout=RICOH_HTTP_TIMEOUT)
    if set_resp.status_code != 200:
        raise HTTPException(status_code=502, detail=f"Ricoh adrsSetUser failed ({set_resp.status_code})")


def _is_plausible_reg(value) -> bool:
    text = str(value or "").strip()
    return text.isdigit() and 1 <= int(text) <= 99999


def _ricoh_parse_entries(text: str) -> list[dict]:
    if not text:
        return []
    entries: list[dict] = []
    pattern = r'\[\s*\d+\s*,\s*"([^"]*)"(?:\s*,\s*"([^"]*)")*\s*\]'
    for match in re.finditer(pattern, text):
        raw_row = match.group(0)
        parts = re.findall(r'"([^"]*)"', raw_row)
        if not parts or len(parts) < 3:
            continue
        reg = parts[0].strip()
        if not reg or not reg.isdigit():
            continue
        entry = {
            "registration_no": reg.zfill(5),
            "name": parts[1].strip() if len(parts) > 1 else "",
            "key_display": parts[2].strip() if len(parts) > 2 else "",
            "freq": True,
            "title1": parts[3].strip() if len(parts) > 3 else None,
            "title2": parts[4].strip() if len(parts) > 4 else None,
            "title3": parts[5].strip() if len(parts) > 5 else None,
            "user_code": parts[6].strip() if len(parts) > 6 else None,
            "email_address": parts[7].strip() if len(parts) > 7 else None,
            "folder": parts[8].strip() if len(parts) > 8 else None,
            "status": "Activo",
        }
        entries.append(entry)
    return entries


def _ricoh_parse_entries_from_html(html: str) -> list[dict]:
    if not html:
        return []
    entries = []
    for row_match in re.finditer(r"<tr[^>]*>(.*?)</tr>", html, re.IGNORECASE | re.DOTALL):
        row_html = row_match.group(1) or ""
        cells = re.findall(r"<td[^>]*>(.*?)</td>", row_html, re.IGNORECASE | re.DOTALL)
        if len(cells) < 3:
            continue
        reg_raw = re.sub(r"<[^>]+>", "", cells[0] or "").strip()
        if not reg_raw.isdigit():
            continue
        entry = {
            "registration_no": reg_raw.zfill(5),
            "name": re.sub(r"<[^>]+>", "", cells[1] or "").strip(),
            "key_display": re.sub(r"<[^>]+>", "", cells[2] or "").strip(),
            "freq": True,
            "title1": None,
            "title2": None,
            "title3": None,
            "user_code": None,
            "email_address": None,
            "folder": None,
            "status": "Activo",
        }
        entries.append(entry)
    return entries


def _ricoh_load_entries_with_browser(printer_ip: str, admin: str | None, password: str | None, diagnostics: list[str]) -> list[dict] | None:
    if not ADDRESS_BOOK_BROWSER_LOGIN_ENABLED:
        diagnostics.append("browser:disabled")
        return None
    try:
        from playwright.sync_api import sync_playwright
    except Exception as ex:
        diagnostics.append(f"browser:unavailable={type(ex).__name__}")
        return None

    login_markers = (
        "authform.cgi",
        "inicio de sesión",
        "contraseña de inicio de sesión",
        "nombre de usuario de inicio de sesión",
    )

    def _safe_text(page) -> str:
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except Exception:
            pass
        try:
            return (page.content() or "").lower()
        except Exception:
            return ""

    def _is_auth_redirect_page(text: str) -> bool:
        t = (text or "").lower()
        return "authform.cgi" in t and ("document.form1.submit" in t or "<form name='form1'" in t or "<form name=\"form1\"" in t)

    candidates = [
        {
            "auth_url": f"http://{printer_ip}/web/guest/es/websys/webArch/authForm.cgi?open=address/adrsList.cgi",
            "page_url": f"http://{printer_ip}/web/entry/es/address/adrsList.cgi",
        },
        {
            "auth_url": f"http://{printer_ip}/web/guest/websys/webArch/authForm.cgi?open=address/adrsList.cgi",
            "page_url": f"http://{printer_ip}/web/entry/address/adrsList.cgi",
        },
    ]

    user, secret = _ricoh_credentials(admin, password)

    with sync_playwright() as pw:
        browser = pw.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 720})
        page = context.new_page()

        for idx, c in enumerate(candidates, start=1):
            try:
                page.goto(c["auth_url"], wait_until="domcontentloaded", timeout=15000)
            except Exception as ex:
                diagnostics.append(f"browser:c{idx}:goto={type(ex).__name__}")
                continue

            page_text = _safe_text(page)
            matched = [m for m in login_markers if m in page_text]
            if not matched and "authform.cgi" not in (page.url or "").lower():
                diagnostics.append(f"browser:c{idx}:no_auth_markers")
                continue

            try:
                user_loc = page.locator("input[name='userid'], input[name='userid_work'], input[id*='user'], input[type='text']").first
                pass_loc = page.locator("input[name='password'], input[name='password_work'], input[id*='pass'], input[type='password']").first
                user_loc.fill(user, timeout=3000)
                pass_loc.fill(secret, timeout=3000)
            except Exception as ex:
                diagnostics.append(f"browser:c{idx}:fill_exc={type(ex).__name__}")
                continue

            submitted = False
            try:
                submit_loc = page.locator("input[type='submit'], button[type='submit']").first
                if submit_loc:
                    try:
                        submit_loc.click(timeout=5000)
                        submitted = True
                    except Exception:
                        submitted = False
                if not submitted:
                    try:
                        page.evaluate("() => { if (document.forms && document.forms[0]) document.forms[0].submit(); }")
                    except Exception:
                        diagnostics.append(f"browser:c{idx}:submit_fail")
                        continue

                try:
                    page.wait_for_timeout(800)
                    page.goto(c["page_url"], wait_until="domcontentloaded", timeout=15000)
                except Exception as ex:
                    diagnostics.append(f"browser:c{idx}:page_exc={type(ex).__name__}")
                    continue

                page_text = _safe_text(page)
                page_url = (page.url or "").lower()
                matched = [m for m in login_markers if m in page_text]
                if matched or "authform.cgi" in page_url or _is_auth_redirect_page(page_text):
                    diagnostics.append(f"browser:c{idx}:markers={','.join((matched or ['authform.cgi'])[:2])}")
                    continue

                cookie_count = 0
                for cookie in context.cookies():
                    name = cookie.get("name")
                    if not name:
                        continue
                    session.cookies.set(
                        name,
                        cookie.get("value") or "",
                        domain=(cookie.get("domain") or printer_ip),
                        path=(cookie.get("path") or "/"),
                    )
                    cookie_count += 1
                diagnostics.append(f"browser:c{idx}:cookies={cookie_count}")
                if cookie_count <= 0:
                    continue

                try:
                    verify = session.get(c["page_url"], timeout=RICOH_HTTP_TIMEOUT)
                    verify_text = (verify.text or "").lower()
                except Exception as ex:
                    diagnostics.append(f"browser:c{idx}:verify_exc={type(ex).__name__}")
                    continue
                if verify.status_code != 200 or _is_auth_redirect_page(verify_text):
                    diagnostics.append(f"browser:c{idx}:verify_auth")
                    continue

                entries = _ricoh_parse_entries(verify_text)
                if not entries:
                    entries = _ricoh_parse_entries_from_html(verify_text)
                diagnostics.append(f"browser:c{idx}:parsed={len(entries)}")
                browser.close()
                return entries

            except Exception as ex:
                diagnostics.append(f"browser:c{idx}:exec_exc={type(ex).__name__}")
                continue

        browser.close()

    diagnostics.append("browser:all_fail")
    return None


@router.post("/{printer_id}/address-book")
def create_address_book_entry(printer_id: int, payload: AddressBookEntryCreate, storage_mode: str | None = Query(default=None), admin: str | None = Query(default=None), password: str | None = Query(default=None), db: Session = Depends(get_db)):
    printer = _get_printer_or_404(db, printer_id)
    storage_mode = _get_storage_mode(storage_mode)
    if storage_mode == "ricoh-real":
        return _create_ricoh_entry(printer, payload, admin, password)
    else:
        entry = _create_local_entry(printer.id, payload)
        return {"entry": entry}


@router.put("/{printer_id}/address-book/{registration_no}")
def update_address_book_entry(printer_id: int, registration_no: str, payload: AddressBookEntryUpdate, storage_mode: str | None = Query(default=None), admin: str | None = Query(default=None), password: str | None = Query(default=None), db: Session = Depends(get_db)):
    printer = _get_printer_or_404(db, printer_id)
    storage_mode = _get_storage_mode(storage_mode)
    if storage_mode == "ricoh-real":
        return _update_ricoh_entry(printer, registration_no, payload, admin, password)
    else:
        entry = _update_local_entry(printer.id, registration_no, payload)
        return {"entry": entry}


@router.delete("/{printer_id}/address-book/{registration_no}")
def delete_address_book_entry(printer_id: int, registration_no: str, storage_mode: str | None = Query(default=None), admin: str | None = Query(default=None), password: str | None = Query(default=None), db: Session = Depends(get_db)):
    printer = _get_printer_or_404(db, printer_id)
    storage_mode = _get_storage_mode(storage_mode)
    if storage_mode == "ricoh-real":
        return _delete_ricoh_entry(printer, registration_no, admin, password)
    else:
        _delete_local_entry(printer.id, registration_no)
        return {"deleted": True}


@router.post("/{printer_id}/address-book/apply")
def apply_address_book_changes(printer_id: int, admin: str | None = Query(default=None), password: str | None = Query(default=None), db: Session = Depends(get_db)):
    printer = _get_printer_or_404(db, printer_id)
    local = _get_local_entries(printer.id)
    if not local:
        return {"applied": False, "message": "No hay cambios locales pendientes", "created": 0, "updated": 0}

    lock = _get_ricoh_session_lock(printer.ip)
    with lock:
        session = _ricoh_build_session(printer.ip)
        try:
            _ricoh_login_address_book(session, printer.ip, admin, password)
            remote = _ricoh_load_entries_with_session(session, printer.ip, dump=False, admin=admin, password=password)
            remote_map = {str(item.get("registration_no") or "").strip().zfill(5): item for item in (remote or [])}

            created_count = 0
            updated_count = 0
            for entry in local:
                reg = str(entry.get("registration_no") or "").strip().zfill(5)
                if reg in remote_map:
                    _ricoh_set_user(session, printer.ip, entry, "MODUSER")
                    updated_count += 1
                else:
                    _ricoh_set_user(session, printer.ip, entry, "ADDUSER")
                    created_count += 1

            return {
                "applied": True,
                "message": "Cambios aplicados exitosamente",
                "created": created_count,
                "updated": updated_count,
            }
        except HTTPException:
            raise
        except Exception as ex:
            raise HTTPException(status_code=502, detail=f"Apply error: {type(ex).__name__}: {str(ex)[:200]}")
        finally:
            try:
                _ricoh_logout_address_book(session, printer.ip)
            except Exception:
                pass


def _create_ricoh_entry(printer, payload: AddressBookEntryCreate, admin: str | None = None, password: str | None = None) -> dict:
    entry = {
        "registration_no": (payload.registration_no or "").strip() or "00001",
        "name": payload.name or "",
        "key_display": payload.key_display or payload.name or "",
        "freq": payload.freq if payload.freq is not None else True,
        "title1": payload.title1,
        "title2": payload.title2,
        "title3": payload.title3,
        "user_code": payload.user_code,
        "email_address": payload.email_address,
        "folder": payload.folder,
        "status": payload.status or "Activo",
    }
    lock = _get_ricoh_session_lock(printer.ip)
    with lock:
        try:
            session = _get_or_create_ricoh_session(printer.ip, admin, password)
            _ricoh_set_user(session, printer.ip, entry, "ADDUSER")
            entries = _ricoh_load_entries_with_session(session, printer.ip, dump=False, admin=admin, password=password)
            return {"entry": entry, "entries": entries or []}
        except Exception as ex:
            # Si falla, limpiar sesión del pool
            _close_ricoh_session(printer.ip)
            raise


def _update_ricoh_entry(printer, registration_no: str, payload: AddressBookEntryUpdate, admin: str | None = None, password: str | None = None) -> dict:
    entry = {
        "registration_no": registration_no,
        "name": payload.name or "",
        "key_display": payload.key_display or payload.name or "",
        "freq": payload.freq if payload.freq is not None else True,
        "title1": payload.title1,
        "title2": payload.title2,
        "title3": payload.title3,
        "user_code": payload.user_code,
        "email_address": payload.email_address,
        "folder": payload.folder,
        "status": payload.status or "Activo",
    }
    lock = _get_ricoh_session_lock(printer.ip)
    with lock:
        try:
            session = _get_or_create_ricoh_session(printer.ip, admin, password)
            _ricoh_set_user(session, printer.ip, entry, "MODUSER")
            entries = _ricoh_load_entries_with_session(session, printer.ip, dump=False, admin=admin, password=password)
            return {"entry": entry, "entries": entries or []}
        except Exception as ex:
            _close_ricoh_session(printer.ip)
            raise


def _delete_ricoh_entry(printer, registration_no: str, admin: str | None = None, password: str | None = None) -> dict:
    reg = str(registration_no).strip().zfill(5)
    lock = _get_ricoh_session_lock(printer.ip)
    with lock:
        try:
            session = _get_or_create_ricoh_session(printer.ip, admin, password)
            list_page = session.get(f"http://{printer.ip}/web/entry/es/address/adrsList.cgi", timeout=RICOH_HTTP_TIMEOUT)
            token = _ricoh_extract_wim_token(list_page.text)
            if not token:
                raise HTTPException(status_code=502, detail="Ricoh wimToken not found")
            delete_payload = {
                "mode": "DELUSER",
                "wimToken": token,
                "entryIndexIn": reg,
                "checkBoxIn": reg,
            }
            resp = session.post(f"http://{printer.ip}/web/entry/es/address/adrsSetUser.cgi", data=delete_payload, timeout=RICOH_HTTP_TIMEOUT)
            if resp.status_code != 200:
                raise HTTPException(status_code=502, detail=f"Ricoh delete user failed ({resp.status_code})")
            entries = _ricoh_load_entries_with_session(session, printer.ip, dump=False, admin=admin, password=password)
            return {"entries": entries or []}
        except Exception as ex:
            _close_ricoh_session(printer.ip)
            raise