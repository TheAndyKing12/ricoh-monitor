from sqlalchemy import inspect, text

from .database import engine


def _text_type() -> str:
    if engine.dialect.name == "mssql":
        return "VARCHAR(MAX)"
    return "TEXT"


def _add_column_sql(table_name: str, column_name: str, column_type: str) -> str:
    if engine.dialect.name == "mssql":
        return f"ALTER TABLE {table_name} ADD {column_name} {column_type}"
    return f"ALTER TABLE {table_name} ADD COLUMN {column_name} {column_type}"


def _add_columns_if_missing(table_name: str, columns: dict[str, str]) -> None:
    inspector = inspect(engine)
    if table_name not in inspector.get_table_names():
        return
    existing = {col["name"] for col in inspector.get_columns(table_name)}
    with engine.begin() as conn:
        for col_name, col_type in columns.items():
            if col_name not in existing:
                conn.execute(text(_add_column_sql(table_name, col_name, col_type)))


def run_startup_migrations() -> None:
    text_type = _text_type()
    _add_columns_if_missing(
        "inventory",
        {"part_number": text_type, "location": text_type, "notes": text_type},
    )

    inspector = inspect(engine)
    if "printer_assets" in inspector.get_table_names():
        existing = {col["name"] for col in inspector.get_columns("printer_assets")}
        with engine.begin() as conn:
            if "physical_port" not in existing:
                conn.execute(text(_add_column_sql("printer_assets", "physical_port", text_type)))
                if "physical_floor" in existing:
                    conn.execute(text("UPDATE printer_assets SET physical_port = physical_floor"))
