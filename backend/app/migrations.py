from sqlalchemy import inspect, text

from .database import engine


def _add_columns_if_missing(table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    with engine.begin() as conn:
        for col_name, col_type in columns.items():
            if col_name not in existing:
                conn.execute(text(f"ALTER TABLE {table_name} ADD COLUMN {col_name} {col_type}"))


def run_startup_migrations() -> None:
    _add_columns_if_missing(
        "inventory",
        {"part_number": "TEXT", "location": "TEXT", "notes": "TEXT"},
    )

    inspector = inspect(engine)
    if "printer_assets" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("printer_assets")}
        with engine.begin() as conn:
            if "physical_port" not in existing:
                conn.execute(text("ALTER TABLE printer_assets ADD COLUMN physical_port TEXT"))
                if "physical_floor" in existing:
                    conn.execute(text("UPDATE printer_assets SET physical_port = physical_floor"))
