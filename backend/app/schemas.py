from pydantic import BaseModel, ConfigDict
from typing import Optional

class InventoryCreate(BaseModel):
    name: str
    model: str
    type: str
    quantity: int
    min_stock: int
    part_number: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None

class InventoryUpdate(BaseModel):
    name: Optional[str] = None
    model: Optional[str] = None
    type: Optional[str] = None
    quantity: Optional[int] = None
    min_stock: Optional[int] = None
    part_number: Optional[str] = None
    location: Optional[str] = None
    notes: Optional[str] = None

class InventoryResponse(InventoryCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)

class TonerControlUpdate(BaseModel):
    check_date: str | None = None
    backup_black: float | None = None
    backup_cyan: float | None = None
    backup_magenta: float | None = None
    backup_yellow: float | None = None
    pedido: str | None = None
    work_order: str | None = None
    notas: str | None = None

class PrinterCreate(BaseModel):
    shared_name: Optional[str] = None
    name: Optional[str] = None
    model: str
    ip: str
    serial: Optional[str] = None
    location: Optional[str] = None
    is_color: bool = False
    snmp_community: str = "public"

class PrinterUpdate(BaseModel):
    shared_name: Optional[str] = None
    name: Optional[str] = None
    model: Optional[str] = None
    ip: Optional[str] = None
    serial: Optional[str] = None
    location: Optional[str] = None
    is_color: Optional[bool] = None
    snmp_community: Optional[str] = None

class PrinterResponse(BaseModel):
    id: int
    shared_name: Optional[str] = None
    name: Optional[str] = None
    model: Optional[str] = None
    ip: str
    serial: Optional[str] = None
    location: Optional[str] = None
    is_color: bool
    snmp_community: str
    model_config = ConfigDict(from_attributes=True)




class PrinterAssetCreate(BaseModel):
    serial: Optional[str] = None
    model: Optional[str] = None
    shared_name: Optional[str] = None
    facility_location: Optional[str] = None
    asset_status: str = "Active"
    volume_number: Optional[str] = None
    static_ip: Optional[str] = None
    switch_name: Optional[str] = None
    physical_port: Optional[str] = None
    bpcs_code: Optional[str] = None
    host_name: Optional[str] = None
    mac_address: Optional[str] = None
    arrival_date: Optional[str] = None
    asset_tag: Optional[str] = None
    notes: Optional[str] = None

class PrinterAssetUpdate(BaseModel):
    serial: Optional[str] = None
    model: Optional[str] = None
    shared_name: Optional[str] = None
    facility_location: Optional[str] = None
    asset_status: Optional[str] = None
    volume_number: Optional[str] = None
    static_ip: Optional[str] = None
    switch_name: Optional[str] = None
    physical_port: Optional[str] = None
    bpcs_code: Optional[str] = None
    host_name: Optional[str] = None
    mac_address: Optional[str] = None
    arrival_date: Optional[str] = None
    asset_tag: Optional[str] = None
    notes: Optional[str] = None

class PrinterAssetResponse(PrinterAssetCreate):
    id: int
    model_config = ConfigDict(from_attributes=True)
