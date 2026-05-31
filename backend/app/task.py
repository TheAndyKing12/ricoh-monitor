from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy.orm import Session
from app.database import SessionLocal
from app import crud
from app.routers import printers as printers_router
from app.config import settings
import logging
from datetime import datetime
from pathlib import Path
import json
import threading
from app.routers.notifications import push_event_sync

logger = logging.getLogger(__name__)
scheduler = BackgroundScheduler()

# Sistema de caché en memoria
cache_lock = threading.Lock()
printer_status_cache = {}  # {printer_id: {status_data, timestamp}}
counters_cache = {}  # {printer_id: {counters_data, timestamp}}
toner_control_cache = []  # Lista de todos los registros de control de tóner
cache_metadata = {
    "last_full_sync": None,
    "last_counter_sync": None,
    "last_toner_sync": None
}
job_stats = {}

# Directorio de caché en disco (backup)
CACHE_DIR = settings.cache_dir
CACHE_DIR.mkdir(exist_ok=True)


def _record_job_start(job_id: str) -> float:
    started = datetime.now()
    job_stats[job_id] = {
        **job_stats.get(job_id, {}),
        "last_started": started.isoformat(),
        "last_finished": None,
        "last_duration_seconds": None,
        "last_error": None,
        "last_success": False,
    }
    return started.timestamp()


def _record_job_finish(job_id: str, started_ts: float, error: Exception | None = None) -> None:
    finished = datetime.now()
    job_stats[job_id] = {
        **job_stats.get(job_id, {}),
        "last_finished": finished.isoformat(),
        "last_duration_seconds": round(finished.timestamp() - started_ts, 2),
        "last_error": str(error) if error else None,
        "last_success": error is None,
    }


def save_cache_to_disk():
    """Guardar caché en disco como backup"""
    try:
        cache_file = CACHE_DIR / "printer_cache.json"
        with cache_lock:
            cache_data = {
                "printer_status": printer_status_cache,
                "counters": counters_cache,
                "toner_control": toner_control_cache,
                "metadata": cache_metadata
            }
        cache_file.write_text(json.dumps(cache_data, indent=2, default=str))
        logger.debug("Cache saved to disk")
    except Exception as e:
        logger.error(f"Error saving cache to disk: {e}")


def load_cache_from_disk():
    """Cargar caché desde disco al iniciar"""
    try:
        cache_file = CACHE_DIR / "printer_cache.json"
        if cache_file.exists():
            cache_data = json.loads(cache_file.read_text())
            with cache_lock:
                global printer_status_cache, counters_cache, toner_control_cache, cache_metadata
                printer_status_cache = cache_data.get("printer_status", {})
                counters_cache = cache_data.get("counters", {})
                toner_control_cache = cache_data.get("toner_control", [])
                cache_metadata.update(cache_data.get("metadata", {}))
            logger.info("✓ Cache loaded from disk")
            return True
    except Exception as e:
        logger.warning(f"Could not load cache from disk: {e}")
    return False


def get_cached_printer_status(printer_id: int = None):
    """Obtener estado de impresoras desde caché"""
    with cache_lock:
        if printer_id:
            return printer_status_cache.get(str(printer_id))
        else:
            # Retornar todos los estados como lista
            return [data for data in printer_status_cache.values()]


def get_cached_counters(printer_id: int = None):
    """Obtener contadores desde caché"""
    with cache_lock:
        if printer_id:
            return counters_cache.get(str(printer_id))
        else:
            return [data for data in counters_cache.values()]


def get_cached_toner_control():
    """Obtener datos de control de tóner desde caché"""
    with cache_lock:
        return toner_control_cache.copy()


def get_cache_metadata():
    """Obtener metadata del caché"""
    with cache_lock:
        return cache_metadata.copy()


def sync_all_printer_status():
    """Sincronizar estado completo de todas las impresoras (SNMP)"""
    started_ts = _record_job_start("sync_printer_status")
    logger.info("=== Starting full printer status sync ===")
    db = SessionLocal()
    updated_cache = {}
    
    try:
        all_printers = crud.get_printers(db)
        success_count = 0
        error_count = 0
        
        for printer in all_printers:
            try:
                # Obtener estado completo vía SNMP
                status = printers_router.build_fast_printer_status(printer)
                
                if status:
                    updated_cache[str(printer.id)] = {
                        **status,
                        "id": printer.id,
                        "cached_at": datetime.now().isoformat()
                    }
                    success_count += 1
                    logger.debug(f"✓ Status cached for {printer.shared_name or printer.ip}")
                else:
                    error_count += 1
                    # Mantener en caché como offline
                    updated_cache[str(printer.id)] = {
                        "id": printer.id,
                        "status": "offline",
                        "error_message": "No SNMP response",
                        "cached_at": datetime.now().isoformat()
                    }
            except Exception as e:
                error_count += 1
                logger.error(f"✗ Error getting status for {printer.shared_name or printer.ip}: {e}")
                updated_cache[str(printer.id)] = {
                    "id": printer.id,
                    "status": "error",
                    "error_message": str(e),
                    "cached_at": datetime.now().isoformat()
                }
             
                
        
        # === Detección de eventos para notificaciones ===
        with cache_lock:
            prev_cache = printer_status_cache.copy()

        for pid, new in updated_cache.items():
            prev = prev_cache.get(pid, {})
            name = new.get("shared_name") or new.get("ip") or pid

            # 🔴 OFFLINE: estatus cambió a offline/error
            new_status = new.get("status", "")
            prev_status = prev.get("status", "")
            if new_status in ("offline", "error") and prev_status not in ("offline", "error"):
                    push_event_sync("offline", {
                    "printer": name,
                    "message": f"{name} está OFFLINE"
                })

            # 🟡 TÓNER CRÍTICO: cualquier color < 10%
            toner_keys = ["toner_black", "toner_cyan", "toner_magenta", "toner_yellow"]
            for key in toner_keys:
                val = new.get(key)
                if val is not None and isinstance(val, (int, float)) and val < 10:
                    color_label = key.replace("toner_", "").capitalize()
                    push_event_sync("toner_critical", {
                        "printer": name,
                        "color": color_label,
                        "value": val,
                        "message": f"{name}: tóner {color_label} crítico ({val}%)"
                    })

            # 🟢 DELTA TÓNER ≥ 10pts
            for key in toner_keys:
                new_val = new.get(key)
                old_val = prev.get(key)
                if new_val is not None and old_val is not None:
                    if isinstance(new_val, (int, float)) and isinstance(old_val, (int, float)):
                        if (new_val - old_val) >= 30:  # subió ≥ 30pts = tóner reemplazado
                            color_label = key.replace("toner_", "").capitalize()
                            push_event_sync("toner_delta", {
                                "printer": name,
                                "color": color_label,
                                "old": old_val,
                                "new": new_val,
                                "message": f"{name}: {color_label} cambió {old_val}% → {new_val}%"
                            })
        # === Fin detección ===

        # Actualizar caché en memoria


        with cache_lock:
            printer_status_cache.clear()
            printer_status_cache.update(updated_cache)
            cache_metadata["last_full_sync"] = datetime.now().isoformat()
        
        # Guardar en disco
        save_cache_to_disk()
        
        logger.info(f"=== Status sync completed: {success_count} success, {error_count} errors ===")
    except Exception as e:
        logger.error(f"Fatal error in sync_all_printer_status: {e}")
        _record_job_finish("sync_printer_status", started_ts, e)
    finally:
        db.close()
        if job_stats.get("sync_printer_status", {}).get("last_finished") is None:
            _record_job_finish("sync_printer_status", started_ts)


def sync_all_printer_counters():
    """Sincronizar contadores de todas las impresoras"""
    started_ts = _record_job_start("sync_counters")
    logger.info("=== Starting counter sync job ===")
    db = SessionLocal()
    updated_cache = {}
    
    try:
        all_printers = crud.get_printers(db)
        success_count = 0
        error_count = 0
        
        for printer in all_printers:
            try:
                # Capturar y guardar contadores en BD
                result = printers_router.build_printer_counters(printer)
                
                if result:
                    # También guardar en caché
                    updated_cache[str(printer.id)] = {
                        **result,
                        "id": printer.id,
                        "cached_at": datetime.now().isoformat()
                    }
                    success_count += 1
                    logger.debug(f"✓ Counters synced for {printer.shared_name or printer.ip}")
                else:
                    error_count += 1
            except Exception as e:
                error_count += 1
                logger.error(f"✗ Error syncing counters for {printer.shared_name or printer.ip}: {e}")
        
        # Actualizar caché
        with cache_lock:
            counters_cache.clear()
            counters_cache.update(updated_cache)
            cache_metadata["last_counter_sync"] = datetime.now().isoformat()
        
        save_cache_to_disk()
        
        logger.info(f"=== Counter sync completed: {success_count} success, {error_count} errors ===")
    except Exception as e:
        logger.error(f"Fatal error in sync_all_printer_counters: {e}")
        _record_job_finish("sync_counters", started_ts, e)
    finally:
        db.close()
        if job_stats.get("sync_counters", {}).get("last_finished") is None:
            _record_job_finish("sync_counters", started_ts)


def sync_all_toner_control():
    """Actualizar caché de control de tóner desde la base de datos"""
    started_ts = _record_job_start("sync_toner_control")
    logger.info("=== Starting toner control cache update ===")
    db = SessionLocal()
    
    try:
        # Obtener todos los registros de toner_control desde BD
        from app.routers.toner_control import get_all_toner_control_records
        
        records = get_all_toner_control_records(db)
        
        with cache_lock:
            toner_control_cache.clear()
            toner_control_cache.extend(records)
            cache_metadata["last_toner_sync"] = datetime.now().isoformat()
        
        save_cache_to_disk()
        
        logger.info(f"=== Toner control cache updated: {len(records)} records ===")
    except Exception as e:
        logger.error(f"Fatal error in sync_all_toner_control: {e}")
        _record_job_finish("sync_toner_control", started_ts, e)
    finally:
        db.close()
        if job_stats.get("sync_toner_control", {}).get("last_finished") is None:
            _record_job_finish("sync_toner_control", started_ts)

def cleanup_old_notifications():
    """Eliminar notificaciones con más de 30 días"""
    started_ts = _record_job_start("cleanup_notifications")
    db = SessionLocal()
    try:
        from app import crud
        crud.delete_old_notifications(db, days=settings.notification_retention_days)
        logger.info("✓ Old notifications cleaned up (>30 days)")
    except Exception as e:
        logger.error(f"Error cleaning notifications: {e}")
        _record_job_finish("cleanup_notifications", started_ts, e)
    finally:
        db.close()
        if job_stats.get("cleanup_notifications", {}).get("last_finished") is None:
            _record_job_finish("cleanup_notifications", started_ts)

def start_scheduler():
    """Iniciar el scheduler de tareas en segundo plano"""
    STATUS_SYNC_INTERVAL = settings.status_sync_interval
    COUNTER_SYNC_INTERVAL = settings.counter_sync_interval
    TONER_SYNC_INTERVAL = settings.toner_sync_interval
    
    # Cargar caché desde disco
    load_cache_from_disk()
    
    # Tarea 1: Sincronizar estado de impresoras (SNMP) - cada 5 minutos
    scheduler.add_job(
        sync_all_printer_status,
        trigger=IntervalTrigger(minutes=STATUS_SYNC_INTERVAL),
        id='sync_printer_status',
        name='Sync all printer status (SNMP)',
        replace_existing=True
    )
    
    # Tarea 2: Sincronizar contadores - cada 30 minutos
    scheduler.add_job(
        sync_all_printer_counters,
        trigger=IntervalTrigger(minutes=COUNTER_SYNC_INTERVAL),
        id='sync_counters',
        name='Sync all printer counters',
        replace_existing=True
    )
    
    # Tarea 3: Sincronizar control de tóner - cada 10 minutos
    scheduler.add_job(
        sync_all_toner_control,
        trigger=IntervalTrigger(minutes=TONER_SYNC_INTERVAL),
        id='sync_toner_control',
        name='Sync toner control cache',
        replace_existing=True
    )
        # Tarea 4: Limpiar notificaciones antiguas - cada 24 horas
    scheduler.add_job(
        cleanup_old_notifications,
        trigger=IntervalTrigger(hours=24),
        id='cleanup_notifications',
        name='Cleanup old notifications (30 days)',
        replace_existing=True
    )
    # Ejecutar sincronización inicial inmediatamente
    scheduler.add_job(
        sync_all_printer_status,
        id='initial_status_sync',
        name='Initial status sync'
    )
    
    scheduler.start()
    logger.info("✓ Background scheduler started successfully")
    logger.info(f"  - Printer status sync: every {STATUS_SYNC_INTERVAL} minutes")
    logger.info(f"  - Counter sync: every {COUNTER_SYNC_INTERVAL} minutes")
    logger.info(f"  - Toner control sync: every {TONER_SYNC_INTERVAL} minutes")


def stop_scheduler():
    """Detener el scheduler"""
    if scheduler.running:
        save_cache_to_disk()  # Guardar caché antes de cerrar
        scheduler.shutdown(wait=False)
        logger.info("✓ Background scheduler stopped")


def get_scheduler_status():
    """Obtener estado de las tareas programadas"""
    if not scheduler.running:
        return {"running": False, "jobs": [], "cache_metadata": cache_metadata, "job_stats": job_stats}
    
    jobs = []
    for job in scheduler.get_jobs():
        jobs.append({
            "id": job.id,
            "name": job.name,
            "next_run": job.next_run_time.isoformat() if job.next_run_time else None,
            "stats": job_stats.get(job.id, {})
        })
    
    return {
        "running": True,
        "jobs": jobs,
        "cache_metadata": cache_metadata,
        "cache_stats": {
            "printer_status_count": len(printer_status_cache),
            "counters_count": len(counters_cache),
            "toner_control_count": len(toner_control_cache)
        },
        "job_stats": job_stats
    }
