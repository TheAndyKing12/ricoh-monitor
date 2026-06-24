import requests
import pytest
from fastapi import HTTPException

from app.routers import address_book


def test_address_book_sort_ignores_invalid_registration_numbers():
    entries = [
        {"registration_no": "00003", "name": "C"},
        {"registration_no": "not-a-number", "name": "bad"},
        {"registration_no": "00000", "name": "zero"},
        {"registration_no": "00001", "name": "A"},
    ]

    assert [item["registration_no"] for item in address_book._sort_entries(entries)] == ["00001", "00003"]


def test_address_book_next_registration_number_uses_highest_existing():
    entries = [{"registration_no": "00003"}, {"registration_no": "00011"}, {"registration_no": "bad"}]

    assert address_book._next_registration_no(entries) == "00012"


def test_address_book_client_session_token_is_scoped_to_printer():
    session = requests.Session()
    token = address_book._register_address_book_client_session("10.0.0.10", session)

    assert address_book._get_address_book_client_session(token, "10.0.0.10") is session
    with pytest.raises(HTTPException) as exc_info:
        address_book._get_address_book_client_session(token, "10.0.0.11")
    assert exc_info.value.status_code == 403
    assert address_book._close_address_book_client_session(token=token) is True


def test_address_book_import_maps_spanish_headers():
    row = {
        "Numero registro": "27",
        "Nombre": "Recepcion",
        "Correo": "recepcion@example.com",
        "Frecuente": "si",
    }

    mapped = address_book._map_address_book_import_row(row)

    assert mapped["registration_no"] == "00027"
    assert mapped["name"] == "Recepcion"
    assert mapped["key_display"] == "Recepcion"
    assert mapped["email_address"] == "recepcion@example.com"
    assert mapped["freq"] is True


def test_address_book_import_parses_csv_with_semicolon():
    raw = "Registration No.;Name;E-mail Address\n1;User One;one@example.com\n".encode("utf-8")

    rows = address_book._parse_address_book_import_file("book.csv", raw)
    mapped = address_book._map_address_book_import_row(rows[0])

    assert mapped["registration_no"] == "00001"
    assert mapped["name"] == "User One"


def test_address_book_import_rejects_missing_name():
    with pytest.raises(ValueError, match="obligatorio"):
        address_book._map_address_book_import_row({"Registration No.": "1"})


def test_address_book_local_crud_roundtrip(tmp_path, monkeypatch):
    monkeypatch.setattr(address_book, "STORE_PATH", tmp_path / "address_book.json")
    created = address_book._create_local_entry(
        10,
        address_book.AddressBookEntryCreate(
            registration_no="00001",
            name="Original",
            email_address="original@example.com",
        ),
    )
    assert created["name"] == "Original"

    updated = address_book._update_local_entry(
        10,
        "00001",
        address_book.AddressBookEntryUpdate(name="Updated", email_address="updated@example.com"),
    )
    assert updated["name"] == "Updated"
    assert address_book._get_local_entries(10)[0]["email_address"] == "updated@example.com"

    address_book._delete_local_entry(10, "00001")
    assert address_book._get_local_entries(10) == []
