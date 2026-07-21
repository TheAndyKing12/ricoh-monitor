from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from concurrent.futures import ThreadPoolExecutor, as_completed
from ..database import SessionLocal
from .. import crud, schemas
from .. import utils
from .. import ricoh_mib
from ..utils import safe_int, detect_is_color, get_db
from ..snmp import get_snmp_values
from .auth import require_tab

router = APIRouter(prefix="/toner-control", tags=["Toner Control"], dependencies=[Depends(require_tab("tonerControl"))])





OID_K = ricoh_mib.OID["marker_black"]
OID_C = ricoh_mib.OID["marker_cyan"]
OID_M = ricoh_mib.OID["marker_magenta"]
OID_Y = ricoh_mib.OID["marker_yellow"]


def _query_printer_toner(ip, community, is_color):
    """Query toner levels for a single printer via SNMP (batch call)."""
    oids = [OID_K, ricoh_mib.OID["ricoh_toner_black"]]
    if is_color:
        oids.extend([
            OID_C,
            OID_M,
            OID_Y,
            ricoh_mib.OID["ricoh_toner_cyan"],
            ricoh_mib.OID["ricoh_toner_magenta"],
            ricoh_mib.OID["ricoh_toner_yellow"],
        ])
    try:
        vals = get_snmp_values(ip, community, oids, timeout=2, retries=0)
    except Exception:
        vals = {}
    return {
        "toner_black": ricoh_mib.choose_toner(vals, "marker_black", "ricoh_toner_black"),
        "toner_cyan": ricoh_mib.choose_toner(vals, "marker_cyan", "ricoh_toner_cyan") if is_color else None,
        "toner_magenta": ricoh_mib.choose_toner(vals, "marker_magenta", "ricoh_toner_magenta") if is_color else None,
        "toner_yellow": ricoh_mib.choose_toner(vals, "marker_yellow", "ricoh_toner_yellow") if is_color else None,
    }


@router.get("/")
def get_controls(db: Session = Depends(get_db)):
    printers = crud.get_printers(db)
    controls = crud.get_toner_controls(db)
    control_map = {c.printer_id: c for c in controls}

    # Pre-compute color detection
    printer_info = []
    for p in printers:
        model_hint = " ".join(str(getattr(p, attr, "") or "") for attr in ("shared_name", "name", "model"))
        if ricoh_mib.model_says_mono(model_hint):
            is_color = False
        else:
            is_color = bool(detect_is_color(p) or ricoh_mib.model_says_color(model_hint))
        printer_info.append((p, is_color))

    # Query all printers in parallel
    toner_data = {}
    with ThreadPoolExecutor(max_workers=min(20, len(printer_info) or 1)) as executor:
        future_map = {
            executor.submit(
                _query_printer_toner, p.ip, p.snmp_community, is_color
            ): p.id
            for p, is_color in printer_info
        }
        for future in as_completed(future_map):
            pid = future_map[future]
            try:
                toner_data[pid] = future.result()
            except Exception:
                toner_data[pid] = {
                    "toner_black": None,
                    "toner_cyan": None,
                    "toner_magenta": None,
                    "toner_yellow": None,
                }

    results = []
    for p, is_color in printer_info:
        td = toner_data.get(p.id, {})
        control = control_map.get(p.id)
        results.append({
            "printer_id": p.id,
            "shared_name": p.shared_name,
            "name": p.name,
            "model": p.model,
            "serial": p.serial,
            "ip": p.ip,
            "location": p.location,
            "is_color": is_color,
            "toner_black": td.get("toner_black"),
            "toner_cyan": td.get("toner_cyan"),
            "toner_magenta": td.get("toner_magenta"),
            "toner_yellow": td.get("toner_yellow"),
            "check_date": control.check_date if control else "",
            "backup_black": control.backup_black if control else 0,
            "backup_cyan": control.backup_cyan if control else 0,
            "backup_magenta": control.backup_magenta if control else 0,
            "backup_yellow": control.backup_yellow if control else 0,
            "pedido": control.pedido if control else "",
            "work_order": control.work_order if control else "",
            "notas": control.notas if control else ""
        })
    return results


@router.put("/{printer_id}")
def update_control(
    printer_id: int,
    data: schemas.TonerControlUpdate,
    db: Session = Depends(get_db)
):
    updated = crud.update_toner_control(db, printer_id, data.dict(exclude_none=True))
    # Obtener nombre de la impresora para el log
    printer = crud.get_printer_by_id(db, printer_id)
    label = printer.shared_name or printer.name or f'ID {printer_id}' if printer else f'ID {printer_id}'
    crud.create_log(db, "toner", "updated", f'Control tóner "{label}" actualizado')
    return updated
 
def get_all_toner_control_records(db: Session):
    """Obtener todos los registros de toner control para caché"""
    from app.models import TonerControl
    
    records = db.query(TonerControl).all()

    result = []
    for record in records:
        result.append({
            "id": record.id,
            "printer_id": record.printer_id,
            "check_date": record.check_date,
            "backup_black": record.backup_black,
            "backup_cyan": record.backup_cyan,
            "backup_magenta": record.backup_magenta,
            "backup_yellow": record.backup_yellow,
            "pedido": record.pedido,
            "work_order": record.work_order,
            "notas": record.notas
        })
    
    return result
