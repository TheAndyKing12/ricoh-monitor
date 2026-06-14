from sqlalchemy.orm import Session
from app.database import SessionLocal


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def safe_int(value):
    try:
        return int(value)
    except Exception:
        return None


def detect_is_color(printer):
    if hasattr(printer, "is_color") and printer.is_color is not None:
        return bool(printer.is_color)
    model_upper = (printer.model or "").upper().strip()
    return (
        model_upper.startswith("IM C")
        or model_upper.startswith("MP C")
        or model_upper.startswith("P C")
        or model_upper.startswith("RICOH IM C")
        or model_upper.startswith("RICOH MP C")
        or model_upper.startswith("RICOH P C")
        or "IM C" in model_upper
        or "MP C" in model_upper
        or "P C" in model_upper
    )


def detect_is_color_from_model(model_str: str):
    model_upper = (model_str or "").upper()
    return (
        "IM C" in model_upper
        or "MP C" in model_upper
        or "P C" in model_upper
    )


def _clean_snmp_text(value):
    if value is None:
        return None
    text = str(value).strip().strip("\x00")
    if not text:
        return None
    lowered = text.lower()
    if "no such" in lowered or "not available" in lowered or lowered in {"none", "null", "-"}:
        return None
    return text


def _normalize_ricoh_model(value):
    text = _clean_snmp_text(value)
    if not text:
        return None
    text = text.replace("RICOH ", "").replace("Ricoh ", "").strip()
    tokens = text.replace(",", " ").replace(";", " ").split()
    for idx, token in enumerate(tokens):
        upper = token.upper()
        if upper in {"IM", "MP", "SP"} and idx + 1 < len(tokens):
            return (tokens[idx] + " " + tokens[idx + 1]).strip()
        if upper == "P" and idx + 1 < len(tokens):
            return (tokens[idx] + " " + tokens[idx + 1]).strip()
    return text[:80]
