from sqlalchemy import Column, Integer, String, Boolean, Float, ForeignKey, DateTime, UniqueConstraint
from .database import Base
class Printer(Base):

    __tablename__ = "printers"

    id = Column(Integer, primary_key=True, index=True)

    shared_name = Column(String, nullable=True)

    name = Column(String, nullable=True)

    model = Column(String, nullable=True)

    ip = Column(String, unique=True, index=True)

    serial = Column(String, nullable=True)

    location = Column(String, nullable=True)

    is_color = Column(Boolean, default=False)

    snmp_community = Column(String, default="public")
 
class InventoryItem(Base):

    __tablename__ = "inventory"

    id = Column(Integer, primary_key=True, index=True)

    name = Column(String)

    model = Column(String)

    type = Column(String)

    quantity = Column(Integer)

    min_stock = Column(Integer)

    part_number = Column(String, nullable=True)

    location = Column(String, nullable=True)

    notes = Column(String, nullable=True)
class TonerControl(Base):

    __tablename__ = "toner_control"

    id = Column(Integer, primary_key=True, index=True)

    printer_id = Column(Integer, ForeignKey("printers.id"), unique=True)

    check_date = Column(String, nullable=True)

    backup_black = Column(Float, default=0)

    backup_cyan = Column(Float, default=0)

    backup_magenta = Column(Float, default=0)

    backup_yellow = Column(Float, default=0)

    pedido = Column(String, nullable=True)

    work_order = Column(String, nullable=True)

    notas = Column(String, nullable=True)


class PrinterCounterSnapshot(Base):

    __tablename__ = "printer_counter_snapshots"

    id = Column(Integer, primary_key=True, index=True)
    printer_id = Column(Integer, ForeignKey("printers.id"), index=True, nullable=False)
    captured_at = Column(DateTime, index=True, nullable=False)
    granularity = Column(String, index=True, nullable=False)  # daily|weekly|monthly
    period_bucket = Column(String, index=True, nullable=False)  # YYYY-MM-DD | YYYY-WW | YYYY-MM

    total_pages = Column(Integer, nullable=True)
    bw_pages = Column(Integer, nullable=True)
    color_pages = Column(Integer, nullable=True)
    copy_bw = Column(Integer, nullable=True)
    copy_color = Column(Integer, nullable=True)
    print_bw = Column(Integer, nullable=True)
    print_color = Column(Integer, nullable=True)

    source = Column(String, nullable=True)  # snmp|http|mixed|fallback
    is_complete = Column(Boolean, default=False)

    __table_args__ = (
        UniqueConstraint("printer_id", "granularity", "period_bucket", name="uq_snapshot_printer_period"),
    )


class PrinterAsset(Base):

    __tablename__ = "printer_assets"

    id = Column(Integer, primary_key=True, index=True)
    serial = Column(String, nullable=True)
    model = Column(String, nullable=True)
    shared_name = Column(String, nullable=True)    
    facility_location = Column(String, nullable=True)
    asset_status = Column(String, default="Active")
    volume_number = Column(String, nullable=True)
    static_ip = Column(String, nullable=True)
    switch_name = Column(String, nullable=True)
    physical_port = Column(String, nullable=True)
    bpcs_code = Column(String, nullable=True)
    host_name = Column(String, nullable=True)
    mac_address = Column(String, nullable=True)
    arrival_date = Column(String, nullable=True)
    asset_tag = Column(String, nullable=True)
    notes = Column(String, nullable=True)


class ActivityLog(Base):
    __tablename__ = "activity_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String, index=True)
    category = Column(String)   # printer | inventory | toner
    action = Column(String)     # created | updated | deleted
    description = Column(String)
class NotificationLog(Base):
    __tablename__ = "notification_logs"
    id = Column(Integer, primary_key=True, index=True)
    timestamp = Column(String, index=True)
    event_type = Column(String)   # offline | toner_critical | toner_delta
    printer = Column(String)
    message = Column(String)

class AppSetting(Base):
    __tablename__ = "app_settings"
    key = Column(String, primary_key=True, index=True)
    value = Column(String, nullable=True)

class SystemUser(Base):
    __tablename__ = "system_users"
    id = Column(Integer, primary_key=True, index=True)
    username = Column(String, unique=True, index=True)  # ej: juan.perez
    display_name = Column(String, nullable=True)
    is_active = Column(Boolean, default=True)
    is_admin = Column(Boolean, default=False)
    allowed_tabs = Column(String, default="dashboard")  # tabs separados por coma