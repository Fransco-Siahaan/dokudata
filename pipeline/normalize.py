"""Normalisation of Indonesian amounts, dates and identifiers (PRD 9.2).

Indonesian documents write thousands with dots and decimals with commas
(``Rp 1.250.000,00``), but English-style ``1,250,000.00`` also appears on
printed POS receipts, so the parser decides per string instead of assuming one
locale.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

MONTHS: dict[str, int] = {
    "jan": 1, "januari": 1, "january": 1,
    "feb": 2, "februari": 2, "february": 2, "peb": 2,
    "mar": 3, "maret": 3, "march": 3,
    "apr": 4, "april": 4,
    "mei": 5, "may": 5,
    "jun": 6, "juni": 6, "june": 6,
    "jul": 7, "juli": 7, "july": 7,
    "agu": 8, "ags": 8, "agt": 8, "agustus": 8, "aug": 8, "august": 8,
    "sep": 9, "sept": 9, "september": 9,
    "okt": 10, "oktober": 10, "oct": 10, "october": 10,
    "nov": 11, "nopember": 11, "november": 11,
    "des": 12, "desember": 12, "dec": 12, "december": 12,
}  # fmt: skip

_CURRENCY_RE = re.compile(r"(?i)\b(rp|idr)\.?\s*")
# A money-like token: optional sign/paren, digits with optional . or , groups.
AMOUNT_TOKEN_RE = re.compile(
    r"(?<![\w/])[-(]?(?:Rp\.?\s?|IDR\s?)?\d{1,3}(?:[.,]\d{3})+(?:[.,]\d{1,2})?(?:,-)?\)?(?![\w/])"
    r"|(?<![\w/.,-])[-(]?(?:Rp\.?\s?|IDR\s?)?\d+(?:[.,]\d{1,2})?(?:,-)?\)?(?![\w/.,])",
    re.IGNORECASE,
)


def _fix_ocr_digits(s: str) -> str:
    """Repair letters OCR commonly confuses with digits, only inside numeric runs."""
    return re.sub(r"(?<=\d)[Oo](?=[\d.,]|$)|(?<=[\d.,])[Oo](?=\d)", "0", s)


def parse_amount(text: str | None) -> float | None:
    """Parse an amount such as ``Rp 1.250.000,00`` -> ``1250000.0``.

    Returns ``None`` when the string has no recognisable number.
    """
    if text is None:
        return None
    s = _fix_ocr_digits(str(text).strip())
    negative = s.startswith("-") or (s.startswith("(") and s.endswith(")"))
    s = _CURRENCY_RE.sub("", s)
    s = s.replace(",-", "").replace(".-", "")
    s = re.sub(r"[^\d.,]", "", s)
    if not s or not re.search(r"\d", s):
        return None
    s = s.strip(".,")
    if "." in s and "," in s:
        dec = "." if s.rfind(".") > s.rfind(",") else ","
        thou = "," if dec == "." else "."
        s = s.replace(thou, "").replace(dec, ".")
    elif "." in s or "," in s:
        sep = "." if "." in s else ","
        groups = s.split(sep)
        if len(groups) > 1 and all(len(g) == 3 for g in groups[1:]) and len(groups[0]) <= 3:
            s = "".join(groups)  # thousands separators only
        elif len(groups) == 2:
            s = groups[0] + "." + groups[1]  # single decimal separator
        else:
            s = "".join(groups[:-1]) + "." + groups[-1]
    try:
        value = float(s)
    except ValueError:
        return None
    return -value if negative else value


def format_idr(value: float | None) -> str:
    if value is None:
        return ""
    whole = f"{abs(value):,.0f}".replace(",", ".")
    frac = abs(value) - int(abs(value))
    out = f"Rp {whole}" + (f",{round(frac * 100):02d}" if frac > 0.004 else "")
    return f"-{out}" if value < 0 else out


def find_amounts(text: str) -> list[tuple[str, float, int, int]]:
    """All amount-like tokens in a line: (raw, value, start, end)."""
    out = []
    for m in AMOUNT_TOKEN_RE.finditer(text):
        raw = m.group(0)
        value = parse_amount(raw)
        if value is not None:
            out.append((raw, value, m.start(), m.end()))
    return out


_NUMERIC_DATE_RE = re.compile(r"(?<!\d)(\d{1,4})[/\-.](\d{1,2})[/\-.](\d{2,4})(?!\d)")
# Only real month names, so "Meja 13 Kamis, 22 Januari 2026" cannot swallow the actual date.
_MONTH_ALT = "|".join(sorted(MONTHS, key=len, reverse=True))
_TEXT_DATE_RE = re.compile(
    rf"(?<!\d)(\d{{1,2}})[\s\-./]*({_MONTH_ALT})(?![a-z])\.?[\s\-./,]*(\d{{2,4}})(?!\d)", re.IGNORECASE
)
_MONTH_FIRST_RE = re.compile(
    r"(?<![A-Za-z])([A-Za-z]{3,9})\.?\s+(\d{1,2}),?\s+(\d{4})(?!\d)"
)  # "Mar 14, 2026"


@dataclass(frozen=True, slots=True)
class DateMatch:
    raw: str
    iso: str
    start: int
    end: int


def _make_date(y: int, m: int, d: int) -> date | None:
    if y < 100:
        y += 2000 if y < 70 else 1900
    if not 1990 <= y <= 2099:  # OCR misreads like "2415" are not dates on a receipt
        return None
    try:
        return date(y, m, d)
    except ValueError:
        return None


def find_dates(text: str) -> list[DateMatch]:
    """Find dates in day-first (Indonesian) order; ISO ``yyyy-mm-dd`` is also accepted."""
    found: list[DateMatch] = []
    for m in _NUMERIC_DATE_RE.finditer(text):
        a, b, c = m.groups()
        if len(a) == 4:
            dt = _make_date(int(a), int(b), int(c))
        else:
            dt = _make_date(int(c), int(b), int(a))
        if dt:
            found.append(DateMatch(m.group(0), dt.isoformat(), m.start(), m.end()))
    # Month names read with digit look-alikes ("Apri1", "0kt"): repair a same-length copy for matching.
    letters = re.sub(r"(?<=[A-Za-z])1(?=[A-Za-z]|\b)", "l", text)
    letters = re.sub(r"(?<=[A-Za-z])0|0(?=[A-Za-z]{2})", "o", letters)
    for m in _TEXT_DATE_RE.finditer(letters):
        d, mon, y = m.groups()
        month = MONTHS.get(mon.lower().rstrip("."))
        if month is None:
            continue
        dt = _make_date(int(y), month, int(d))
        if dt:
            found.append(DateMatch(text[m.start() : m.end()], dt.isoformat(), m.start(), m.end()))
    for m in _MONTH_FIRST_RE.finditer(text):
        mon, d, y = m.groups()
        month = MONTHS.get(mon.lower())
        if month is None or any(f.start <= m.start() < f.end for f in found):
            continue
        dt = _make_date(int(y), month, int(d))
        if dt:
            found.append(DateMatch(m.group(0), dt.isoformat(), m.start(), m.end()))
    found.sort(key=lambda x: x.start)
    return found


def parse_date(text: str | None) -> str | None:
    """Normalise ``14 Mar 2026`` / ``14/03/26`` / ``14-03-2026`` to ``2026-03-14``."""
    if not text:
        return None
    s = str(text).strip()
    if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s):
        y, m, d = (int(p) for p in s.split("-"))
        dt = _make_date(y, m, d)
        return dt.isoformat() if dt else None
    matches = find_dates(s)
    return matches[0].iso if matches else None


def normalize_text(text: str | None) -> str | None:
    if text is None:
        return None
    s = re.sub(r"\s+", " ", str(text)).strip(" \t\n:;,-")
    return s or None


def normalize_vendor(text: str | None) -> str | None:
    """Clean whitespace and shouting capitals while keeping the original wording."""
    s = normalize_text(text)
    if s is None:
        return None
    if s.isupper() and len(s) > 3:
        keep_upper = {"PT", "CV", "UD", "TB", "PD", "TBK", "KUD", "RM"}
        s = " ".join(w if w.strip(".,") in keep_upper else w.capitalize() for w in s.split())
    return s


def text_key(text: str | None) -> str:
    """Comparison key: case-folded alphanumerics only (``PT. Maju-Jaya`` == ``pt maju jaya``)."""
    if not text:
        return ""
    return re.sub(r"[^0-9a-z]", "", str(text).casefold())


def normalize_tax_id(text: str | None) -> str | None:
    """Return the NPWP as digits only, or ``None`` if it has no digits."""
    if not text:
        return None
    digits = re.sub(r"\D", "", _fix_ocr_digits(str(text)))
    return digits or None


def format_npwp(digits: str) -> str:
    if len(digits) == 15:
        return f"{digits[:2]}.{digits[2:5]}.{digits[5:8]}.{digits[8]}-{digits[9:12]}.{digits[12:]}"
    return digits


def is_valid_npwp(text: str | None) -> bool:
    digits = normalize_tax_id(text)
    return digits is not None and len(digits) in (15, 16)


PAYMENT_METHODS: dict[str, str] = {
    "tunai": "cash", "cash": "cash",
    "debit": "debit_card", "debet": "debit_card", "edc": "debit_card",
    "kredit": "credit_card", "credit": "credit_card", "visa": "credit_card", "mastercard": "credit_card",
    "qris": "qris",
    "transfer": "bank_transfer", "trf": "bank_transfer",
    "ovo": "e_wallet", "gopay": "e_wallet", "dana": "e_wallet", "shopeepay": "e_wallet", "linkaja": "e_wallet",
}  # fmt: skip


def normalize_payment_method(text: str | None) -> str | None:
    if not text:
        return None
    low = text.casefold()
    for key, value in PAYMENT_METHODS.items():
        if re.search(rf"\b{key}\b", low):
            return value
    return None
