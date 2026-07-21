from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pathlib import Path
from pydantic import BaseModel
from sqlalchemy.orm import Session
import csv
import io
import time

from ..database import SessionLocal
from .. import crud, schemas
from ..utils import get_db
from .auth import require_tab

router = APIRouter(prefix="/printer-assets", tags=["PrinterAssets"], dependencies=[Depends(require_tab("printerAssets"))])


class CSVImportPayload(BaseModel):
    content: str
    filename: str | None = None


ASSET_IMPORT_FIELDS = [
    "serial",
    "model",
    "shared_name",
    "facility_location",
    "asset_status",
    "volume_number",
    "static_ip",
    "switch_name",
    "physical_port",
    "bpcs_code",
    "host_name",
    "mac_address",
    "arrival_date",
    "asset_tag",
    "notes",
]


def _csv_value(row: dict, *names: str) -> str:
    normalized = {str(k).strip().lower().replace(" ", "_"): v for k, v in row.items()}
    for name in names:
        value = normalized.get(name.strip().lower().replace(" ", "_"))
        if value is not None:
            return str(value).strip()
    return ""


def _decode_csv_content(content: str) -> list[dict]:
    text = (content or "").lstrip("\ufeff")
    try:
        dialect = csv.Sniffer().sniff(text[:2048], delimiters=",;\t")
    except csv.Error:
        dialect = csv.excel
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    if not reader.fieldnames:
        raise HTTPException(status_code=400, detail="El archivo CSV no tiene encabezados")
    return list(reader)


def _downloads_dir() -> Path:
    downloads = Path.home() / "Downloads"
    downloads.mkdir(parents=True, exist_ok=True)
    return downloads


def _unique_download_path(filename: str) -> Path:
    path = _downloads_dir() / filename
    if not path.exists():
        return path
    stem = path.stem
    suffix = path.suffix
    for index in range(1, 1000):
        candidate = path.with_name(f"{stem}_{index}{suffix}")
        if not candidate.exists():
            return candidate
    return path.with_name(f"{stem}_{int(time.time())}{suffix}")


def _build_assets_bulk_csv(db: Session) -> str:
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.DictWriter(output, fieldnames=ASSET_IMPORT_FIELDS)
    writer.writeheader()
    for asset in crud.get_printer_assets(db):
        writer.writerow({field: getattr(asset, field, "") or "" for field in ASSET_IMPORT_FIELDS})
    return output.getvalue()


def _find_existing_asset(db: Session, row: dict):
    serial = _csv_value(row, "serial", "serie")
    static_ip = _csv_value(row, "static_ip", "ip")
    asset_tag = _csv_value(row, "asset_tag")
    assets = crud.get_printer_assets(db)
    for asset in assets:
        if serial and (asset.serial or "").strip().lower() == serial.lower():
            return asset
        if static_ip and (asset.static_ip or "").strip().lower() == static_ip.lower():
            return asset
        if asset_tag and (asset.asset_tag or "").strip().lower() == asset_tag.lower():
            return asset
    return None


@router.post("/")
def create_asset(asset: schemas.PrinterAssetCreate, db: Session = Depends(get_db)):
    return crud.create_printer_asset(db, asset)


@router.get("/")
def list_assets(db: Session = Depends(get_db)):
    return crud.get_printer_assets(db)


@router.get("/bulk/export/csv")
def export_assets_bulk_csv(db: Session = Depends(get_db)):
    output = io.StringIO(_build_assets_bulk_csv(db))
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=printer_assets.csv"},
    )


@router.get("/bulk/export/csv/downloads")
def export_assets_bulk_csv_to_downloads(db: Session = Depends(get_db)):
    path = _unique_download_path("printer_assets.csv")
    path.write_text(_build_assets_bulk_csv(db), encoding="utf-8")
    return {"ok": True, "path": str(path)}


@router.post("/bulk/import/csv")
def import_assets_bulk_csv(payload: CSVImportPayload, db: Session = Depends(get_db)):
    created = 0
    updated = 0
    skipped = 0
    errors = []
    rows = _decode_csv_content(payload.content)

    for index, row in enumerate(rows, start=2):
        try:
            data = {
                "serial": _csv_value(row, "serial", "serie") or None,
                "model": _csv_value(row, "model", "modelo") or None,
                "shared_name": _csv_value(row, "shared_name", "shared name") or None,
                "facility_location": _csv_value(row, "facility_location", "ubicacion", "ubicación", "location") or None,
                "asset_status": _csv_value(row, "asset_status", "estado") or "Active",
                "volume_number": _csv_value(row, "volume_number", "vol_n") or None,
                "static_ip": _csv_value(row, "static_ip", "ip") or None,
                "switch_name": _csv_value(row, "switch_name", "switch") or None,
                "physical_port": _csv_value(row, "physical_port", "puerto") or None,
                "bpcs_code": _csv_value(row, "bpcs_code", "bpcs") or None,
                "host_name": _csv_value(row, "host_name", "hostname") or None,
                "mac_address": _csv_value(row, "mac_address", "mac") or None,
                "arrival_date": _csv_value(row, "arrival_date", "fecha_llegada") or None,
                "asset_tag": _csv_value(row, "asset_tag") or None,
                "notes": _csv_value(row, "notes", "notas") or None,
            }
            if not any(data.get(key) for key in ("serial", "shared_name", "static_ip", "asset_tag")):
                skipped += 1
                errors.append({"row": index, "error": "Se requiere serial, shared_name, static_ip o asset_tag"})
                continue

            existing = _find_existing_asset(db, row)
            if existing:
                crud.update_printer_asset(db, existing.id, schemas.PrinterAssetUpdate(**data))
                updated += 1
            else:
                crud.create_printer_asset(db, schemas.PrinterAssetCreate(**data))
                created += 1
        except Exception as exc:
            skipped += 1
            errors.append({"row": index, "error": str(exc)[:200]})

    crud.create_log(db, "printer_asset", "imported", f"Importacion CSV de inventario de impresoras: {created} creadas, {updated} actualizadas, {skipped} omitidas")
    return {"created": created, "updated": updated, "skipped": skipped, "errors": errors}


@router.get("/{asset_id}")
def get_asset(asset_id: int, db: Session = Depends(get_db)):
    asset = crud.get_printer_asset_by_id(db, asset_id)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset no encontrado")
    return asset


@router.put("/{asset_id}")
def update_asset(asset_id: int, data: schemas.PrinterAssetUpdate, db: Session = Depends(get_db)):
    asset = crud.update_printer_asset(db, asset_id, data)
    if not asset:
        raise HTTPException(status_code=404, detail="Asset no encontrado")
    return asset


@router.delete("/{asset_id}")
def delete_asset(asset_id: int, db: Session = Depends(get_db)):
    crud.delete_printer_asset(db, asset_id)
    return {"message": "Deleted"}


@router.get("/export/csv")
def export_assets_csv(db: Session = Depends(get_db)):
    assets = crud.get_printer_assets(db)
    output = io.StringIO()
    output.write("\ufeff")
    writer = csv.writer(output)
    writer.writerow([
        "Serial", "Shared Name", "Ubicación", "Estado",
        "Vol N", "Static IP", "Switch", "Physical Port",
        "BPCs", "Host Name", "MAC Address", "Fecha llegada",
        "Asset Tag", "Notas"
    ])
    for a in assets:
        writer.writerow([
            a.serial or "", a.shared_name or "",
            a.facility_location or "", a.asset_status or "",
            a.volume_number or "", a.static_ip or "",
            a.switch_name or "", a.physical_port or "",
            a.bpcs_code or "", a.host_name or "",
            a.mac_address or "", a.arrival_date or "",
            a.asset_tag or "", a.notes or ""
        ])
    output.seek(0)
    return StreamingResponse(
        output,
        media_type="text/csv",
        headers={"Content-Disposition": "attachment; filename=printer_assets.csv"}
    )
