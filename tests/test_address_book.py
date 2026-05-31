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
