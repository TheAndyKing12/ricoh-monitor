from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
from ..database import SessionLocal
from .. import crud, schemas
from .auth import require_tab

router = APIRouter(prefix="/inventory", tags=["Inventory"], dependencies=[Depends(require_tab("inventory"))])


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


@router.post("/")
def create_item(item: schemas.InventoryCreate, db: Session = Depends(get_db)):
    created = crud.create_inventory(db, item)
    crud.create_log(db, "inventory", "created", f'Item "{created.name}" ({created.model}) agregado — qty: {created.quantity}')
    return created


@router.get("/")
def list_inventory(db: Session = Depends(get_db)):
    return crud.get_inventory(db)


@router.put("/{item_id}")
def update_item(item_id: int, data: schemas.InventoryUpdate, db: Session = Depends(get_db)):
    item = crud.update_inventory(db, item_id, data)
    if not item:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail="Item no encontrado")
    crud.create_log(db, "inventory", "updated", f'Item "{item.name}" ({item.model}) actualizado — qty: {item.quantity}')
    return item


@router.delete("/{item_id}")
def delete_item(item_id: int, db: Session = Depends(get_db)):
    item = crud.get_inventory(db)
    item = next((i for i in item if i.id == item_id), None)
    label = f'Item "{item.name}" ({item.model}) eliminado' if item else f'Item #{item_id} eliminado'
    crud.delete_inventory(db, item_id)
    crud.create_log(db, "inventory", "deleted", label)
    return {"message": "Deleted"}
