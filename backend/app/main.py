from fastapi import FastAPI, HTTPException, BackgroundTasks, Depends
import logging
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import threading
import time
from contextlib import asynccontextmanager
from datetime import datetime, timedelta
from sqlalchemy import text

from fastapi.middleware.cors import CORSMiddleware

from .config import settings as app_settings, BASE_DIR
from .database import Base, engine, SessionLocal
from .migrations import run_startup_migrations

from . import crud
from .routers import printers, inventory, toner_control, address_book, printer_assets, logs, notifications, settings, auth
from .routers.auth import require_admin, require_tab
from app.task import (
    start_scheduler, stop_scheduler, get_scheduler_status,
    sync_all_printer_status, sync_all_printer_counters, sync_all_toner_control,
    get_cached_printer_status, get_cached_counters, get_cached_toner_control,
    get_cache_metadata
)

# Configurar logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)


run_startup_migrations()
Base.metadata.create_all(bind=engine)


def _validate_startup_config():
    warnings = []
    if app_settings.secret_key == "ricoh-monitor-change-me":
        warnings.append("APP_SECRET_KEY sigue siendo el valor por defecto. Cambialo en backend/.env para produccion.")
    if not app_settings.emergency_admin_password:
        warnings.append("EMERGENCY_ADMIN_PASSWORD no esta configurada. No se podra iniciar sesion como admin de emergencia.")
    for w in warnings:
        logging.warning("⚠  %s", w)
    return warnings


@asynccontextmanager
async def lifespan(app: FastAPI):
    _validate_startup_config()
    logging.info("Iniciando scheduler de sincronizacion automatica...")
    start_scheduler()
    _start_daily_snapshot_worker()
    try:
        yield
    finally:
        logging.info("Deteniendo scheduler...")
        _stop_daily_snapshot_worker()
        stop_scheduler()


app = FastAPI(title=app_settings.app_name, version=app_settings.app_version, lifespan=lifespan)


@app.get("/health")
def health_check():
    db_ok = True
    db_error = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    scheduler = get_scheduler_status()
    cache_metadata = get_cache_metadata()
    return {
        "status": "ok" if db_ok else "degraded",
        "app": app_settings.app_name,
        "version": app_settings.app_version,
        "database": {"ok": db_ok, "error": db_error},
        "scheduler": {"running": scheduler.get("running", False), "jobs": len(scheduler.get("jobs", []))},
        "cache": cache_metadata,
        "time": datetime.now().isoformat(),
    }


@app.get("/system/health-center")
def system_health_center(token=Depends(require_admin)):
    db_ok = True
    db_error = None
    try:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
    except Exception as exc:
        db_ok = False
        db_error = str(exc)

    scheduler = get_scheduler_status()
    metadata = get_cache_metadata()
    status_cache = get_cached_printer_status()
    counter_cache = get_cached_counters()
    toner_cache = get_cached_toner_control()

    printers_count = len(status_cache or [])
    offline_count = len([p for p in (status_cache or []) if (p.get("status") or "").lower() in {"offline", "error"}])
    low_toner_count = 0
    for row in status_cache or []:
        toner_values = [
            row.get("toner_black"),
            row.get("toner_cyan"),
            row.get("toner_magenta"),
            row.get("toner_yellow"),
        ]
        if any(isinstance(v, (int, float)) and v < 30 for v in toner_values):
            low_toner_count += 1

    db = SessionLocal()
    try:
        recent_errors = [
            {
                "id": item.id,
                "timestamp": item.timestamp,
                "category": item.category,
                "action": item.action,
                "description": item.description,
            }
            for item in crud.get_logs(db, action="error", limit=10)
        ]
        recent_activity = [
            {
                "id": item.id,
                "timestamp": item.timestamp,
                "category": item.category,
                "action": item.action,
                "description": item.description,
            }
            for item in crud.get_logs(db, limit=10)
        ]
    finally:
        db.close()

    return {
        "status": "ok" if db_ok and scheduler.get("running", False) else "degraded",
        "time": datetime.now().isoformat(),
        "api": {"ok": True, "version": app_settings.app_version},
        "database": {"ok": db_ok, "error": db_error},
        "scheduler": scheduler,
        "cache": {
            **metadata,
            "printer_status_count": printers_count,
            "counter_count": len(counter_cache or []),
            "toner_control_count": len(toner_cache or []),
        },
        "printers": {
            "total": printers_count,
            "offline": offline_count,
            "low_toner": low_toner_count,
        },
        "recent_errors": recent_errors,
        "recent_activity": recent_activity,
    }


# ========== EVENTOS DE INICIO/CIERRE ==========

async def startup_event():
    """Iniciar scheduler al arrancar la aplicación"""
    logging.info("🚀 Iniciando scheduler de sincronización automática...")
    start_scheduler()


async def shutdown_event():
    """Detener scheduler al cerrar la aplicación"""
    logging.info("🛑 Deteniendo scheduler...")
    stop_scheduler()


# ========== ENDPOINTS DE CACHÉ ==========

@app.get("/cache/printer-status")
def get_cached_status(printer_id: int = None, token=Depends(require_tab("dashboard", "printers"))):
    """Obtener estado de impresoras desde caché (ultra rápido)"""
    data = get_cached_printer_status(printer_id)
    metadata = get_cache_metadata()
    
    if printer_id:
        if not data:
            raise HTTPException(status_code=404, detail="Printer not found in cache")
        return {"data": data, "cached_at": metadata.get("last_full_sync")}
    else:
        return {
            "data": data,
            "cached_at": metadata.get("last_full_sync"),
            "count": len(data)
        }


@app.get("/cache/counters")
def get_cached_printer_counters(printer_id: int = None, token=Depends(require_tab("counters"))):
    """Obtener contadores desde caché"""
    data = get_cached_counters(printer_id)
    metadata = get_cache_metadata()
    
    if printer_id:
        if not data:
            raise HTTPException(status_code=404, detail="Counters not found in cache")
        return {"data": data, "cached_at": metadata.get("last_counter_sync")}
    else:
        return {
            "data": data,
            "cached_at": metadata.get("last_counter_sync"),
            "count": len(data)
        }


@app.get("/cache/toner-control")
def get_cached_toner_data(token=Depends(require_tab("tonerControl"))):
    """Obtener datos de control de tóner desde caché"""
    data = get_cached_toner_control()
    metadata = get_cache_metadata()
    
    return {
        "data": data,
        "cached_at": metadata.get("last_toner_sync"),
        "count": len(data)
    }


# ========== ENDPOINTS DE SINCRONIZACIÓN MANUAL ==========

def _log_system_action(action: str, description: str) -> None:
    db = SessionLocal()
    try:
        crud.create_log(db, "system", action, description)
    finally:
        db.close()


@app.post("/scheduler/sync-status-now")
async def trigger_status_sync(background_tasks: BackgroundTasks, token=Depends(require_admin)):
    """Forzar sincronización de estado inmediata"""
    background_tasks.add_task(sync_all_printer_status)
    _log_system_action("sync_status", f"Sincronizacion manual de estado solicitada por {token.get('sub', 'admin')}")
    return {"message": "Status sync triggered"}


@app.post("/scheduler/sync-counters-now")
async def trigger_counter_sync(background_tasks: BackgroundTasks, token=Depends(require_admin)):
    """Forzar sincronización de contadores inmediata"""
    background_tasks.add_task(sync_all_printer_counters)
    _log_system_action("sync_counters", f"Sincronizacion manual de contadores solicitada por {token.get('sub', 'admin')}")
    return {"message": "Counter sync triggered"}


@app.post("/scheduler/sync-toner-now")
async def trigger_toner_sync(background_tasks: BackgroundTasks, token=Depends(require_admin)):
    """Forzar sincronización de tóner inmediata"""
    background_tasks.add_task(sync_all_toner_control)
    _log_system_action("sync_toner", f"Sincronizacion manual de toner solicitada por {token.get('sub', 'admin')}")
    return {"message": "Toner sync triggered"}


@app.get("/scheduler/status")
def scheduler_status(token=Depends(require_admin)):
    """Ver estado de las tareas programadas y caché"""
    return get_scheduler_status()


# ========== DAILY SNAPSHOT WORKER ==========

_DAILY_SNAPSHOT_STOP_EVENT = threading.Event()
_DAILY_SNAPSHOT_THREAD: threading.Thread | None = None


def _seconds_until_next_daily_capture(now: datetime | None = None) -> float:
    now = now or datetime.now()
    target = now.replace(hour=0, minute=5, second=0, microsecond=0)
    if now >= target:
        target = target + timedelta(days=1)
    return max(30.0, (target - now).total_seconds())


def _daily_snapshot_worker():
    while not _DAILY_SNAPSHOT_STOP_EVENT.is_set():
        wait_seconds = _seconds_until_next_daily_capture()
        if _DAILY_SNAPSHOT_STOP_EVENT.wait(wait_seconds):
            break
        try:
            printers.capture_counters_snapshot_now()
        except Exception:
            pass
        time.sleep(1)


def _start_daily_snapshot_worker():
    global _DAILY_SNAPSHOT_THREAD
    if _DAILY_SNAPSHOT_THREAD and _DAILY_SNAPSHOT_THREAD.is_alive():
        return
    _DAILY_SNAPSHOT_STOP_EVENT.clear()
    _DAILY_SNAPSHOT_THREAD = threading.Thread(target=_daily_snapshot_worker, daemon=True)
    _DAILY_SNAPSHOT_THREAD.start()


def _stop_daily_snapshot_worker():
    _DAILY_SNAPSHOT_STOP_EVENT.set()
    global _DAILY_SNAPSHOT_THREAD
    if _DAILY_SNAPSHOT_THREAD and _DAILY_SNAPSHOT_THREAD.is_alive():
        _DAILY_SNAPSHOT_THREAD.join(timeout=2)


# ========== MIDDLEWARE Y ROUTERS ==========

app.add_middleware(
    CORSMiddleware,
    allow_origins=app_settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(printers.router)
app.include_router(inventory.router)
app.include_router(toner_control.router)
app.include_router(address_book.router)
app.include_router(printer_assets.router)
app.include_router(logs.router)
app.include_router(notifications.router)
app.include_router(settings.router)
app.include_router(auth.router)

# Mount frontend static files so dashboard can be served at /frontend/dashboard.html
try:
    frontend_dir = Path(__file__).resolve().parents[2] / "frontend"
    if frontend_dir.exists():
        app.mount("/frontend", StaticFiles(directory=str(frontend_dir), html=True), name="frontend")
except Exception:
    # ignore mounting errors in environments where filesystem layout differs
    pass
