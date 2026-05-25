from sqlalchemy.orm import Session

from . import models, schemas

 
def create_inventory(db: Session, item):

    db_item = models.InventoryItem(**item.dict())

    db.add(db_item)

    db.commit()

    db.refresh(db_item)

    return db_item


def get_inventory(db: Session):

    return db.query(models.InventoryItem).all()


def delete_inventory(db: Session, item_id: int):

    item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()

    if item:

        db.delete(item)

        db.commit()


def update_inventory(db: Session, item_id: int, data: schemas.InventoryUpdate):

    item = db.query(models.InventoryItem).filter(models.InventoryItem.id == item_id).first()

    if not item:

        return None

    for key, value in data.dict(exclude_unset=True).items():

        setattr(item, key, value)

    db.commit()

    db.refresh(item)

    return item
def get_toner_controls(db: Session):

    return db.query(models.TonerControl).all()


def update_toner_control(db: Session, printer_id: int, data: dict):

    control = db.query(models.TonerControl).filter(

        models.TonerControl.printer_id == printer_id

    ).first()

    if not control:

        control = models.TonerControl(printer_id=printer_id)

        db.add(control)

    for key, value in data.items():

        setattr(control, key, value)

    db.commit()

    db.refresh(control)

    return control
def create_printer(db: Session, printer: schemas.PrinterCreate):
   db_printer = models.Printer(
       shared_name=printer.shared_name,
       name=printer.name,
       model=printer.model,
       ip=printer.ip,
       serial=printer.serial,
       location=printer.location,
       is_color=printer.is_color,
       snmp_community=printer.snmp_community
   )
   db.add(db_printer)
   db.commit()
   db.refresh(db_printer)
   return db_printer

def get_printers(db: Session):
   return db.query(models.Printer).order_by(models.Printer.id.asc()).all()

def get_printer_by_id(db: Session, printer_id: int):
   return db.query(models.Printer).filter(models.Printer.id == printer_id).first()

def get_printer_by_ip(db: Session, ip: str):
   return db.query(models.Printer).filter(models.Printer.ip == ip).first()

def update_printer(db: Session, printer_id: int, data: dict):
   printer = db.query(models.Printer).filter(models.Printer.id == printer_id).first()
   if not printer:
       return None
   for key, value in data.items():
       setattr(printer, key, value)
   db.commit()
   db.refresh(printer)
   return printer

def delete_printer(db: Session, printer_id: int):
   printer = db.query(models.Printer).filter(models.Printer.id == printer_id).first()
   if printer:
       db.delete(printer)
       db.commit()   


# --- PrinterAsset CRUD ---

def create_printer_asset(db: Session, asset: schemas.PrinterAssetCreate):
    db_asset = models.PrinterAsset(**asset.dict())
    db.add(db_asset)
    db.commit()
    db.refresh(db_asset)
    return db_asset

def get_printer_assets(db: Session):
    return db.query(models.PrinterAsset).order_by(models.PrinterAsset.id.asc()).all()

def get_printer_asset_by_id(db: Session, asset_id: int):
    return db.query(models.PrinterAsset).filter(models.PrinterAsset.id == asset_id).first()

def update_printer_asset(db: Session, asset_id: int, data: schemas.PrinterAssetUpdate):
    asset = db.query(models.PrinterAsset).filter(models.PrinterAsset.id == asset_id).first()
    if not asset:
        return None
    for key, value in data.dict(exclude_unset=True).items():
        setattr(asset, key, value)
    db.commit()
    db.refresh(asset)
    return asset

def delete_printer_asset(db: Session, asset_id: int):
    asset = db.query(models.PrinterAsset).filter(models.PrinterAsset.id == asset_id).first()
    if asset:
        db.delete(asset)
        db.commit()

def create_log(db: Session, category: str, action: str, description: str):
    from datetime import datetime
    log = models.ActivityLog(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        category=category,
        action=action,
        description=description
    )
    db.add(log)
    db.commit()
    return log


def get_logs(db: Session, category: str = None, limit: int = 200):
    query = db.query(models.ActivityLog).order_by(models.ActivityLog.id.desc())
    if category:
        query = query.filter(models.ActivityLog.category == category)
    return query.limit(limit).all() 
def save_notification(db: Session, event_type: str, printer: str, message: str):
    from datetime import datetime
    log = models.NotificationLog(
        timestamp=datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        event_type=event_type,
        printer=printer,
        message=message
    )
    db.add(log)
    db.commit()
    return log


def get_notifications(db: Session, event_type: str = None, limit: int = 500):
    query = db.query(models.NotificationLog).order_by(models.NotificationLog.id.desc())
    if event_type:
        query = query.filter(models.NotificationLog.event_type == event_type)
    return query.limit(limit).all()


def delete_old_notifications(db: Session, days: int = 30):
    from datetime import datetime, timedelta
    cutoff = (datetime.now() - timedelta(days=days)).strftime("%Y-%m-%d %H:%M:%S")
    db.query(models.NotificationLog).filter(models.NotificationLog.timestamp < cutoff).delete()
    db.commit()