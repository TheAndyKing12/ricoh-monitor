import sys
from pathlib import Path

from sqlalchemy import text

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))

from app.database import engine


def main() -> None:
    with engine.connect() as conn:
        value = conn.execute(text("SELECT 1")).scalar()
    print(f"database ok: {value}")
    print(f"dialect: {engine.dialect.name}")


if __name__ == "__main__":
    main()
