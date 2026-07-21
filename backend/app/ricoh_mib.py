from __future__ import annotations

from dataclasses import dataclass
import re

from .utils import _clean_snmp_text, _normalize_ricoh_model, safe_int


OID = {
    # Standard MIB-II / Printer-MIB
    "sys_descr": "1.3.6.1.2.1.1.1.0",
    "sys_name": "1.3.6.1.2.1.1.5.0",
    "hr_descr_1": "1.3.6.1.2.1.25.3.2.1.3.1",
    "hr_descr_2": "1.3.6.1.2.1.25.3.2.1.3.2",
    "printer_name": "1.3.6.1.2.1.43.5.1.1.16.1",
    "printer_serial": "1.3.6.1.2.1.43.5.1.1.17.1",
    "printer_total": "1.3.6.1.2.1.43.10.2.1.4.1.1",
    "printer_state": "1.3.6.1.2.1.25.3.5.1.1.1",
    "printer_error_state": "1.3.6.1.2.1.25.3.5.1.2.1",
    "marker_black": "1.3.6.1.2.1.43.11.1.1.9.1.1",
    "marker_cyan": "1.3.6.1.2.1.43.11.1.1.9.1.2",
    "marker_magenta": "1.3.6.1.2.1.43.11.1.1.9.1.3",
    "marker_yellow": "1.3.6.1.2.1.43.11.1.1.9.1.4",
    "alert_severity": "1.3.6.1.2.1.43.18.1.1.2.1.1",
    "alert_training": "1.3.6.1.2.1.43.18.1.1.3.1.1",
    "alert_description": "1.3.6.1.2.1.43.18.1.1.8.1.1",
    # Ricoh private MIB, mapped from SmartDeviceMonitor/RMAdmin.
    "ricoh_sys_name": "1.3.6.1.4.1.367.3.2.1.1.1.1",
    "ricoh_sys_version": "1.3.6.1.4.1.367.3.2.1.1.1.2",
    "ricoh_nic_name": "1.3.6.1.4.1.367.3.2.1.6.1.1.7",
    "ricoh_nic_description": "1.3.6.1.4.1.367.3.2.1.6.1.1.8",
    "ricoh_nic_firmware": "1.3.6.1.4.1.367.3.2.1.6.1.1.4",
    "ricoh_ip": "1.3.6.1.4.1.367.3.2.1.7.2.1.17",
    "ricoh_netmask": "1.3.6.1.4.1.367.3.2.1.7.2.1.20",
    "ricoh_mac": "1.3.6.1.4.1.367.3.2.1.7.2.1.7",
    "ricoh_toner_black": "1.3.6.1.4.1.367.3.2.1.2.24.1.1.5.1",
    "ricoh_toner_cyan": "1.3.6.1.4.1.367.3.2.1.2.24.1.1.5.2",
    "ricoh_toner_magenta": "1.3.6.1.4.1.367.3.2.1.2.24.1.1.5.3",
    "ricoh_toner_yellow": "1.3.6.1.4.1.367.3.2.1.2.24.1.1.5.4",
    "ricoh_bw_pages": "1.3.6.1.4.1.367.3.2.1.7.2.9.1.2.1",
    "ricoh_color_pages": "1.3.6.1.4.1.367.3.2.1.7.2.9.1.2.3",
    "ricoh_printer_capability": "1.3.6.1.4.1.367.3.2.1.2.13.3",
    "ricoh_scan_color_capability": "1.3.6.1.4.1.367.3.2.1.2.16.1",
}


IDENTITY_OIDS = [
    OID["sys_descr"],
    OID["sys_name"],
    OID["hr_descr_1"],
    OID["hr_descr_2"],
    OID["printer_name"],
    OID["printer_serial"],
    OID["marker_cyan"],
    OID["ricoh_sys_name"],
    OID["ricoh_sys_version"],
    OID["ricoh_nic_name"],
    OID["ricoh_nic_description"],
]

STATUS_OIDS = [
    OID["marker_black"],
    OID["printer_state"],
    OID["printer_error_state"],
    OID["alert_severity"],
    OID["alert_training"],
    OID["alert_description"],
    OID["ricoh_toner_black"],
]

COLOR_STATUS_OIDS = [
    OID["marker_cyan"],
    OID["marker_magenta"],
    OID["marker_yellow"],
    OID["ricoh_toner_cyan"],
    OID["ricoh_toner_magenta"],
    OID["ricoh_toner_yellow"],
]

COUNTER_OIDS = [
    OID["printer_total"],
    OID["ricoh_bw_pages"],
    OID["ricoh_color_pages"],
]


def first_present(values: dict, *keys_or_oids: str):
    for key in keys_or_oids:
        value = values.get(OID.get(key, key))
        if value is not None:
            return value
    return None


def normalize_toner(value):
    number = safe_int(value)
    if number is None:
        return None
    if number < 0:
        return None
    if number > 100:
        return None
    return number


def model_says_color(model_text: str | None) -> bool:
    text = (model_text or "").upper()
    return "IM C" in text or "MP C" in text or "P C" in text or bool(re.search(r"\bC\d{3,5}\b", text))


def model_says_mono(model_text: str | None) -> bool:
    text = (model_text or "").upper()
    if model_says_color(text):
        return False
    return (
        "BNW" in text
        or "B/N" in text
        or "B&W" in text
        or "BLACK" in text
        or "MONO" in text
        or bool(re.search(r"\bIM\s*\d{3,5}\b", text))
        or bool(re.search(r"\bMP\s*\d{3,5}\b", text))
    )


def infer_color_capability(model_text: str | None, cyan_toner=None, color_counter=None):
    if model_says_mono(model_text):
        return False
    if model_says_color(model_text):
        return True
    if normalize_toner(cyan_toner) is not None:
        return True
    color_value = safe_int(color_counter)
    if color_value is not None and color_value > 0:
        return True
    return None


def parse_identity(values: dict) -> dict:
    name = (
        _clean_snmp_text(first_present(values, "ricoh_nic_name"))
        or _clean_snmp_text(first_present(values, "sys_name"))
        or _clean_snmp_text(first_present(values, "printer_name"))
        or _clean_snmp_text(first_present(values, "ricoh_sys_name"))
    )
    model = (
        _normalize_ricoh_model(first_present(values, "hr_descr_1"))
        or _normalize_ricoh_model(first_present(values, "hr_descr_2"))
        or _normalize_ricoh_model(first_present(values, "printer_name"))
        or _normalize_ricoh_model(first_present(values, "ricoh_nic_description"))
        or _normalize_ricoh_model(first_present(values, "sys_descr"))
        or _normalize_ricoh_model(first_present(values, "ricoh_sys_version"))
    )
    serial = _clean_snmp_text(first_present(values, "printer_serial"))
    is_color = infer_color_capability(model, first_present(values, "marker_cyan"))
    return {"name": name, "model": model, "serial": serial, "is_color": is_color}


def choose_toner(values: dict, standard_key: str, ricoh_key: str):
    standard = normalize_toner(first_present(values, standard_key))
    if standard is not None:
        return standard
    return normalize_toner(first_present(values, ricoh_key))


def parse_status_alert(values: dict) -> str | None:
    description = _clean_snmp_text(first_present(values, "alert_description"))
    severity = safe_int(first_present(values, "alert_severity"))
    training = safe_int(first_present(values, "alert_training"))
    if description and description.lower() not in {"unknown", "none"}:
        return description
    if severity and severity >= 3:
        return "Alerta de impresora"
    if training:
        return f"Alerta de impresora ({training})"
    return None


@dataclass
class CounterReading:
    total_pages: int | None = None
    bw_pages: int | None = None
    color_pages: int | None = None
    source: str = "none"
    warnings: list[str] | None = None


def normalize_counter_reading(values: dict, *, model_text: str | None, db_is_color: bool | None):
    total_pages = safe_int(first_present(values, "printer_total"))
    bw_pages = safe_int(first_present(values, "ricoh_bw_pages"))
    color_pages = safe_int(first_present(values, "ricoh_color_pages"))
    warnings: list[str] = []

    live_color = infer_color_capability(model_text, color_counter=color_pages)
    is_color = bool(db_is_color) if db_is_color is not None else bool(live_color)
    if live_color is False:
        is_color = False
    elif live_color is True:
        is_color = True

    if not is_color:
        if bw_pages is None and total_pages is not None:
            bw_pages = total_pages
        if bw_pages is not None:
            total_pages = bw_pages
        color_pages = None
    else:
        if color_pages is None and total_pages is not None and bw_pages is not None:
            derived = total_pages - bw_pages
            if derived >= 0:
                color_pages = derived
                warnings.append("color_derived_from_total_minus_bw")
        if bw_pages is not None and color_pages is not None:
            combined = bw_pages + color_pages
            if total_pages is not None and abs(combined - total_pages) > max(10, int(total_pages * 0.05)):
                warnings.append("total_does_not_match_bw_plus_color")
            total_pages = combined

    source = "snmp" if any(v is not None for v in (total_pages, bw_pages, color_pages)) else "none"
    return CounterReading(total_pages, bw_pages, color_pages, source, warnings), is_color
