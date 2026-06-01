from pathlib import Path
import ast
import importlib
import os
import sys

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
CHECK_DB = ROOT / "tmp" / "check_backend.db"
CHECK_DB.parent.mkdir(exist_ok=True)
os.environ.setdefault("DATABASE_URL", f"sqlite:///{CHECK_DB.as_posix()}")
os.environ.setdefault("APP_SECRET_KEY", "check-secret")
sys.path.insert(0, str(BACKEND))


def check_python_syntax() -> None:
    for path in (BACKEND / "app").rglob("*.py"):
        if "venv" in path.parts or "__pycache__" in path.parts:
            continue
        ast.parse(path.read_text(encoding="utf-8"), filename=str(path))


def check_imports() -> None:
    required = [
        "apscheduler",
        "fastapi",
        "jose",
        "ldap3",
        "openpyxl",
        "pyodbc",
        "requests",
        "sqlalchemy",
        "uvicorn",
    ]
    missing = []
    for module in required:
        try:
            importlib.import_module(module)
        except Exception as exc:
            missing.append(f"{module}: {exc}")
    if missing:
        raise SystemExit("Dependencias faltantes:\n" + "\n".join(missing))


def check_app_import() -> None:
    import app.main  # noqa: F401


if __name__ == "__main__":
    check_python_syntax()
    check_imports()
    check_app_import()
    print("backend ok")
