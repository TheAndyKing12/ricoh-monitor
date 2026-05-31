from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse
import asyncio
import json
from datetime import datetime
import requests
from sqlalchemy.orm import Session
from app.config import settings
from app.database import SessionLocal
from app import crud

router = APIRouter(prefix="/notifications", tags=["Notifications"])

# Cola global de eventos en memoria
_subscribers: list[asyncio.Queue] = []
_subscribers_lock = asyncio.Lock()

TONER_DELTA_THRESHOLD = 10  # puntos de cambio para notificar


async def push_event(event_type: str, printer_name: str, message: str, level: str = "info"):
    """Enviar evento a todos los clientes SSE conectados"""
    payload = json.dumps({
        "type": event_type,
        "printer": printer_name,
        "message": message,
        "level": level,  # error | warning | success | info
        "timestamp": datetime.now().strftime("%H:%M:%S")
    })
    dead = []
    async with _subscribers_lock:
        for q in _subscribers:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead.append(q)
        for q in dead:
            _subscribers.remove(q)


def push_event_sync(event_type: str, data: dict):
    """Versión sync para llamar desde task.py (hilo de scheduler) — guarda en DB"""
    try:
        # Guardar en base de datos
        from app.database import SessionLocal
        from app import crud
        db = SessionLocal()
        try:
            crud.save_notification(
                db,
                event_type=event_type,
                printer=data.get("printer", ""),
                message=data.get("message", "")
            )
        finally:
            db.close()

        if settings.alert_webhook_url:
            try:
                requests.post(
                    settings.alert_webhook_url,
                    json={
                        "type": event_type,
                        "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                        **data,
                    },
                    timeout=settings.alert_webhook_timeout_seconds,
                )
            except Exception:
                pass

        # Enviar a clientes SSE conectados
        payload = json.dumps({
            "type": event_type,
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            **data
        })
        loop = asyncio.get_event_loop()
        if loop.is_running():
            async def _push():
                async with _subscribers_lock:
                    dead = []
                    for q in _subscribers:
                        try:
                            q.put_nowait(payload)
                        except asyncio.QueueFull:
                            dead.append(q)
                    for q in dead:
                        _subscribers.remove(q)
            asyncio.run_coroutine_threadsafe(_push(), loop)
    except Exception as e:
        pass


@router.get("/stream")
async def notification_stream():
    """SSE endpoint — el frontend se conecta aquí para recibir notificaciones"""
    queue: asyncio.Queue = asyncio.Queue(maxsize=50)

    async with _subscribers_lock:
        _subscribers.append(queue)

    async def event_generator():
        try:
            # Ping inicial para confirmar conexión
            yield "data: {\"type\": \"connected\", \"message\": \"Notificaciones activas\"}\n\n"
            while True:
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=25.0)
                    yield f"data: {payload}\n\n"
                except asyncio.TimeoutError:
                    # Keepalive ping cada 25s
                    yield ": ping\n\n"
        except asyncio.CancelledError:
            pass
        finally:
            async with _subscribers_lock:
                if queue in _subscribers:
                    _subscribers.remove(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        }
    )

@router.get("/history")
def get_notification_history(event_type: str = None, limit: int = 500):
    """Historial completo de notificaciones (últimos 30 días)"""
    db = SessionLocal()
    try:
        records = crud.get_notifications(db, event_type=event_type, limit=limit)
        return [
            {
                "id": r.id,
                "timestamp": r.timestamp,
                "event_type": r.event_type,
                "printer": r.printer,
                "message": r.message
            }
            for r in records
        ]
    finally:
        db.close()


@router.post("/test")
def create_test_notification():
    data = {
        "printer": "Sistema",
        "message": "Notificacion de prueba enviada correctamente",
    }
    push_event_sync("test", data)
    return {"ok": True, **data}
