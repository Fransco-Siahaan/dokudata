import pytest

from pipeline.normalize import (
    find_amounts,
    format_idr,
    is_valid_npwp,
    normalize_payment_method,
    normalize_tax_id,
    normalize_vendor,
    parse_amount,
    parse_date,
    text_key,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Rp 1.250.000,00", 1250000.0),
        ("1.250.000", 1250000.0),
        ("1,250,000.00", 1250000.0),
        ("125.000,-", 125000.0),
        ("Rp1.250", 1250.0),
        ("12,5", 12.5),
        ("0,50", 0.5),
        ("(10.000)", -10000.0),
        ("-Rp 5.000", -5000.0),
        ("1.25O.000", 1250000.0),  # OCR read a zero as the letter O
        ("IDR 2.000.000", 2000000.0),
        ("", None),
        ("Rp", None),
        (None, None),
    ],
)
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == expected


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("14 Mar 2026", "2026-03-14"),
        ("14/03/26", "2026-03-14"),
        ("14-03-2026", "2026-03-14"),
        ("14.03.2026", "2026-03-14"),
        ("2026-03-14", "2026-03-14"),
        ("Sabtu, 14 Maret 2026", "2026-03-14"),
        ("14 Agt 2025", "2025-08-14"),
        ("Mar 14, 2026", "2026-03-14"),
        ("03/04/26", "2026-04-03"),  # day first
        ("31/02/2026", None),
        ("bukan tanggal", None),
    ],
)
def test_parse_date(raw, expected):
    assert parse_date(raw) == expected


def test_find_amounts_skips_text_and_keeps_order():
    found = find_amounts("2 x 65.000 130.000")
    assert [v for _, v, _, _ in found] == [2.0, 65000.0, 130000.0]


def test_format_idr_roundtrip():
    assert format_idr(1250000) == "Rp 1.250.000"
    assert parse_amount(format_idr(1250000.5)) == 1250000.5


def test_vendor_normalisation_keeps_legal_forms():
    assert normalize_vendor("  TOKO   MAJU JAYA ") == "Toko Maju Jaya"
    assert normalize_vendor("PT. SINAR ABADI") == "PT. Sinar Abadi"
    assert text_key("PT. Maju-Jaya") == text_key("pt maju jaya")


def test_npwp():
    assert normalize_tax_id("01.234.567.8-901.234") == "012345678901234"
    assert is_valid_npwp("01.234.567.8-901.234")
    assert is_valid_npwp("1234567890123456")
    assert not is_valid_npwp("12345")


@pytest.mark.parametrize(
    ("text", "method"),
    [("TUNAI 50.000", "cash"), ("QRIS", "qris"), ("DEBIT BCA", "debit_card"), ("Transfer bank", "bank_transfer"),
     ("GOPAY", "e_wallet"), ("Terima kasih", None)],
)  # fmt: skip
def test_payment_method(text, method):
    assert normalize_payment_method(text) == method


def test_dates_survive_ocr_look_alikes_and_weekday_names():
    assert parse_date("6 Apri1 2026-20:19 / TRX505707") == "2026-04-06"
    assert parse_date("Meja 13 Kamis, 22 Januari 2026") == "2026-01-22"
    assert parse_date("14 0kt 2025") == "2025-10-14"
    assert parse_date("22/06/2415") is None  # implausible year from a misread
