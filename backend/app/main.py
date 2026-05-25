from fastapi import FastAPI, HTTPException, BackgroundTasks
import logging
from fastapi.staticfiles import StaticFiles
from pathlib import Path
import threading
import time
from datetime import datetime, timedelta

from fastapi.middleware.cors import CORSMiddleware

from .database import Base, engine

from .routers import printers, inventory, toner_control, address_book, printer_assets, logs, notifications, settings , auth
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


def _migrate_inventory_columns():
    """Add new nullable columns to inventory table if they don't exist yet."""
    import sqlalchemy
    insp = sqlalchemy.inspect(engine)
    if "inventory" in insp.get_table_names():
        existing = {col["name"] for col in insp.get_columns("inventory")}
        new_cols = {"part_number": "TEXT", "location": "TEXT", "notes": "TEXT"}
        with engine.begin() as conn:
            for col_name, col_type in new_cols.items():
                if col_name not in existing:
                    conn.execute(sqlalchemy.text(f"ALTER TABLE inventory ADD COLUMN {col_name} {col_type}"))

_migrate_inventory_columns()


def _migrate_printer_assets_columns():
    """Rename physical_floor -> physical_port and handle removed ci column."""
    import sqlalchemy
    insp = sqlalchemy.inspect(engine)
    if "printer_assets" not in insp.get_table_names():
        return
    existing = {col["name"] for col in insp.get_columns("printer_assets")}
    with engine.begin() as conn:
        if "physical_port" not in existing:
            conn.execute(sqlalchemy.text("ALTER TABLE printer_assets ADD COLUMN physical_port TEXT"))
            if "physical_floor" in existing:
                conn.execute(sqlalchemy.text("UPDATE printer_assets SET physical_port = physical_floor"))

_migrate_printer_assets_columns()


Base.metadata.create_all(bind=engine)

app = FastAPI(title="Ricoh Monitor")


# ========== EVENTOS DE INICIO/CIERRE ==========

@app.on_event("startup")
async def startup_event():
    """Iniciar scheduler al arrancar la aplicación"""
    logging.info("🚀 Iniciando scheduler de sincronización automática...")
    start_scheduler()


@app.on_event("shutdown")
async def shutdown_event():
    """Detener scheduler al cerrar la aplicación"""
    logging.info("🛑 Deteniendo scheduler...")
    stop_scheduler()


# ========== ENDPOINTS DE CACHÉ ==========

@app.get("/cache/printer-status")
def get_cached_status(printer_id: int = None):
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
def get_cached_printer_counters(printer_id: int = None):
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
def get_cached_toner_data():
    """Obtener datos de control de tóner desde caché"""
    data = get_cached_toner_control()
    metadata = get_cache_metadata()
    
    return {
        "data": data,
        "cached_at": metadata.get("last_toner_sync"),
        "count": len(data)
    }


# ========== ENDPOINTS DE SINCRONIZACIÓN MANUAL ==========

@app.post("/scheduler/sync-status-now")
async def trigger_status_sync(background_tasks: BackgroundTasks):
    """Forzar sincronización de estado inmediata"""
    background_tasks.add_task(sync_all_printer_status)
    return {"message": "Status sync triggered"}


@app.post("/scheduler/sync-counters-now")
async def trigger_counter_sync(background_tasks: BackgroundTasks):
    """Forzar sincronización de contadores inmediata"""
    background_tasks.add_task(sync_all_printer_counters)
    return {"message": "Counter sync triggered"}


@app.post("/scheduler/sync-toner-now")
async def trigger_toner_sync(background_tasks: BackgroundTasks):
    """Forzar sincronización de tóner inmediata"""
    background_tasks.add_task(sync_all_toner_control)
    return {"message": "Toner sync triggered"}


@app.get("/scheduler/status")
def scheduler_status():
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


@app.on_event("startup")
def _start_daily_snapshot_worker():
    global _DAILY_SNAPSHOT_THREAD
    if _DAILY_SNAPSHOT_THREAD and _DAILY_SNAPSHOT_THREAD.is_alive():
        return
    _DAILY_SNAPSHOT_STOP_EVENT.clear()
    _DAILY_SNAPSHOT_THREAD = threading.Thread(target=_daily_snapshot_worker, daemon=True)
    _DAILY_SNAPSHOT_THREAD.start()


@app.on_event("shutdown")
def _stop_daily_snapshot_worker():
    _DAILY_SNAPSHOT_STOP_EVENT.set()
    global _DAILY_SNAPSHOT_THREAD
    if _DAILY_SNAPSHOT_THREAD and _DAILY_SNAPSHOT_THREAD.is_alive():
        _DAILY_SNAPSHOT_THREAD.join(timeout=2)


# ========== MIDDLEWARE Y ROUTERS ==========

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
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