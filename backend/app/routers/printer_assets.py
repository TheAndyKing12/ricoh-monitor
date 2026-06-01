from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session
import csv
import io

from ..database import SessionLocal
from .. import crud, schemas
from .auth import require_tab

router = APIRouter(prefix="/printer-assets", tags=["PrinterAssets"], dependencies=[Depends(require_tab("printerAssets"))])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
def create_asset(asset: schemas.PrinterAssetCreate, db: Session = Depends(get_db)):
    return crud.create_printer_asset(db, asset)


@router.get("/")
def list_assets(db: Session = Depends(get_db)):
    return crud.get_printer_assets(db)


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
        "ID", "Serial", "Shared Name", "Ubicación", "Estado",
        "Vol N", "Static IP", "Switch", "Physical Port",
        "BPCs", "Host Name", "MAC Address", "Fecha llegada",
        "Asset Tag", "Notas"
    ])
    for a in assets:
        writer.writerow([
            a.id, a.serial or "", a.shared_name or "",
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
