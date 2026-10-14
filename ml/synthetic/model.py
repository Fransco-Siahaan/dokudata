"""Sampling a synthetic document and its ground truth."""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ml.synthetic import vocab

MONTHS_ID = ["Januari", "Februari", "Maret", "April", "Mei", "Juni", "Juli", "Agustus", "September", "Oktober",
             "November", "Desember"]  # fmt: skip
MONTHS_ID_ABBR = ["Jan", "Feb", "Mar", "Apr", "Mei", "Jun", "Jul", "Agu", "Sep", "Okt", "Nov", "Des"]
MONTHS_EN_ABBR = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
DAYS_ID = ["Senin", "Selasa", "Rabu", "Kamis", "Jumat", "Sabtu", "Minggu"]

DATE_STYLES = [
    "dmy_slash",
    "dmy_dash",
    "dmy_short",
    "d_mon_y",
    "d_month_y",
    "iso",
    "dmy_dot",
    "day_d_month_y",
]
AMOUNT_STYLES = ["id", "id_dec", "rp_id", "rp_id_dec", "id_dash", "en", "plain"]

PAYMENT_DISPLAY = {
    "cash": ["TUNAI", "CASH", "Tunai"],
    "debit_card": ["DEBIT BCA", "KARTU DEBIT", "EDC MANDIRI"],
    "credit_card": ["KARTU KREDIT", "CREDIT CARD VISA"],
    "qris": ["QRIS"],
    "bank_transfer": ["TRANSFER BANK", "Transfer"],
    "e_wallet": ["GOPAY", "OVO", "DANA", "SHOPEEPAY"],
}


def fmt_date(d: date, style: str) -> str:
    match style:
        case "dmy_slash":
            return d.strftime("%d/%m/%Y")
        case "dmy_dash":
            return d.strftime("%d-%m-%Y")
        case "dmy_short":
            return d.strftime("%d/%m/%y")
        case "d_mon_y":
            return f"{d.day:02d} {MONTHS_ID_ABBR[d.month - 1]} {d.year}"
        case "d_month_y":
            return f"{d.day} {MONTHS_ID[d.month - 1]} {d.year}"
        case "iso":
            return d.isoformat()
        case "dmy_dot":
            return d.strftime("%d.%m.%Y")
        case "day_d_month_y":
            return f"{DAYS_ID[d.weekday()]}, {d.day} {MONTHS_ID[d.month - 1]} {d.year}"
        case "en_mon":
            return f"{MONTHS_EN_ABBR[d.month - 1]} {d.day:02d}, {d.year}"
    raise ValueError(style)


def fmt_amount(v: float, style: str, force_rp: bool = False) -> str:
    whole = int(round(abs(v)))
    id_whole = f"{whole:,}".replace(",", ".")
    match style:
        case "id":
            s = id_whole
        case "id_dec":
            s = f"{id_whole},00"
        case "rp_id":
            s = f"Rp {id_whole}"
        case "rp_id_dec":
            s = f"Rp {id_whole},00"
        case "id_dash":
            s = f"{id_whole},-"
        case "en":
            s = f"{whole:,}"
        case "plain":
            s = str(whole)
        case _:
            raise ValueError(style)
    if force_rp and not s.startswith("Rp"):
        s = f"Rp {s}"
    return f"-{s}" if v < 0 else s


def terbilang(n: int) -> str:
    """Spell out an amount in Indonesian (``1250000`` -> ``satu juta dua ratus lima puluh ribu``)."""
    units = [
        "",
        "satu",
        "dua",
        "tiga",
        "empat",
        "lima",
        "enam",
        "tujuh",
        "delapan",
        "sembilan",
        "sepuluh",
        "sebelas",
    ]

    def words(x: int) -> str:
        if x < 12:
            return units[x]
        if x < 20:
            return f"{units[x - 10]} belas"
        if x < 100:
            return f"{units[x // 10]} puluh {words(x % 10)}".strip()
        if x < 200:
            return f"seratus {words(x - 100)}".strip()
        if x < 1000:
            return f"{units[x // 100]} ratus {words(x % 100)}".strip()
        if x < 2000:
            return f"seribu {words(x - 1000)}".strip()
        if x < 1_000_000:
            return f"{words(x // 1000)} ribu {words(x % 1000)}".strip()
        if x < 1_000_000_000:
            return f"{words(x // 1_000_000)} juta {words(x % 1_000_000)}".strip()
        return f"{words(x // 1_000_000_000)} miliar {words(x % 1_000_000_000)}".strip()

    return " ".join(words(n).split()) or "nol"


@dataclass
class Item:
    description: str
    qty: int
    unit_price: int
    amount: int


@dataclass
class SynthDoc:
    doc_id: str
    doc_type: str  # receipt | invoice | other
    template: str
    unseen: bool
    vendor_name: str = ""
    vendor_street: str = ""
    vendor_city: str = ""
    vendor_phone: str = ""
    vendor_npwp: str | None = None
    customer: str | None = None
    customer_street: str = ""
    customer_city: str = ""
    number: str | None = None
    issue_date: date | None = None
    due_date: date | None = None
    items: list[Item] = field(default_factory=list)
    subtotal: int = 0
    discount: int = 0
    tax_rate: float = 0.0
    tax_amount: int = 0
    total: int = 0
    payment_method: str | None = None
    payment_display: str | None = None
    cash_paid: int | None = None
    change: int | None = None
    cashier: str = ""
    date_style: str = "dmy_slash"
    amount_style: str = "id"
    time_str: str = ""
    bank: str = ""
    injection: str | None = None
    other_kind: str | None = None
    extra: dict[str, Any] = field(default_factory=dict)

    def amt(self, v: float, force_rp: bool = False) -> str:
        return fmt_amount(v, self.amount_style, force_rp)

    def dt(self, d: date | None) -> str:
        return fmt_date(d, self.date_style) if d else ""

    def ground_truth(self) -> dict[str, Any]:
        if self.doc_type == "other":
            return {"document_type": "other"}
        return {
            "document_type": self.doc_type,
            "vendor_name": self.vendor_name,
            "vendor_tax_id": self.vendor_npwp,
            "document_number": self.number,
            "issue_date": self.issue_date.isoformat() if self.issue_date else None,
            "due_date": self.due_date.isoformat() if self.due_date else None,
            "currency": "IDR",
            "subtotal": float(self.subtotal) if self.extra.get("show_subtotal", True) else None,
            "discount": float(self.discount) if self.discount else None,
            "tax_amount": float(self.tax_amount) if self.tax_amount else None,
            "total": float(self.total),
            "payment_method": self.payment_method,
            "line_items": [
                {"description": it.description, "qty": float(it.qty), "unit_price": float(it.unit_price),
                 "amount": float(it.amount)}
                for it in self.items
            ],
        }  # fmt: skip


def _random_date(rng: random.Random) -> date:
    start = date(2024, 1, 1)
    end = date(2026, 9, 30)
    return start + timedelta(days=rng.randint(0, (end - start).days))


def _items(rng: random.Random, category: str, n: int) -> list[Item]:
    pool = vocab.ITEMS[category]
    chosen = rng.sample(pool, min(n, len(pool)))
    out = []
    for desc, lo, hi, maxq in chosen:
        step = 500 if hi < 100000 else 5000
        price = rng.randrange(lo // step, hi // step + 1) * step
        qty = rng.randint(1, maxq)
        out.append(Item(desc, qty, price, qty * price))
    return out


def _totals(doc: SynthDoc, rng: random.Random, p_discount: float, p_tax: float) -> None:
    doc.subtotal = sum(it.amount for it in doc.items)
    if rng.random() < p_discount:
        if rng.random() < 0.5:
            doc.discount = int(round(doc.subtotal * rng.choice([0.05, 0.1, 0.15]) / 100) * 100)
        else:
            doc.discount = rng.choice([2000, 5000, 10000, 25000, 50000])
        doc.discount = min(doc.discount, doc.subtotal // 2)
    if rng.random() < p_tax:
        doc.tax_rate = rng.choice([0.11, 0.11, 0.12])
        doc.tax_amount = int(round((doc.subtotal - doc.discount) * doc.tax_rate))
    doc.total = doc.subtotal - doc.discount + doc.tax_amount


def sample_receipt(doc_id: str, template: str, rng: random.Random, unseen: bool) -> SynthDoc:
    name, category = vocab.receipt_vendor(rng, unseen)
    street, city = vocab.address(rng)
    doc = SynthDoc(
        doc_id, "receipt", template, unseen, vendor_name=name, vendor_street=street, vendor_city=city
    )
    doc.vendor_phone = vocab.phone(rng)
    doc.vendor_npwp = vocab.npwp_digits(rng) if rng.random() < 0.3 else None
    d = _random_date(rng)
    doc.issue_date = d
    doc.time_str = f"{rng.randint(7, 21):02d}:{rng.randint(0, 59):02d}"
    doc.number = rng.choice([
        f"{rng.randint(1, 9999):04d}",
        f"NT-{d:%Y%m%d}-{rng.randint(1, 9999):04d}",
        f"TRX{rng.randint(100000, 999999)}",
        f"S/{d:%Y}/{d:%m}/{rng.randint(1, 9999):04d}",
        f"{rng.randint(1, 9)}{rng.randint(10000000, 99999999)}",
    ]) if rng.random() < 0.88 else None  # fmt: skip
    doc.items = _items(rng, category, rng.choice([1, 2, 3, 3, 4, 5, 6, 7, 8]))
    _totals(doc, rng, p_discount=0.25, p_tax=0.45)
    doc.payment_method = (
        rng.choice(["cash", "cash", "cash", "debit_card", "qris", "e_wallet", "credit_card"])
        if rng.random() < 0.85
        else None
    )
    if doc.payment_method:
        doc.payment_display = rng.choice(PAYMENT_DISPLAY[doc.payment_method])
    if doc.payment_method == "cash":
        step = rng.choice([5000, 10000, 50000, 100000])
        doc.cash_paid = ((doc.total // step) + rng.choice([0, 1, 1, 2])) * step
        doc.cash_paid = max(doc.cash_paid, doc.total)
        doc.change = doc.cash_paid - doc.total
    doc.cashier = rng.choice(vocab.PERSON_FIRST)
    doc.date_style = rng.choice(DATE_STYLES)
    doc.amount_style = rng.choice(AMOUNT_STYLES)
    return doc


def sample_invoice(doc_id: str, template: str, rng: random.Random, unseen: bool) -> SynthDoc:
    name = vocab.invoice_vendor(rng, unseen)
    street, city = vocab.address(rng)
    doc = SynthDoc(
        doc_id, "invoice", template, unseen, vendor_name=name, vendor_street=street, vendor_city=city
    )
    doc.vendor_phone = vocab.phone(rng)
    doc.vendor_npwp = vocab.npwp_digits(rng) if rng.random() < 0.8 else None
    doc.customer = vocab.invoice_vendor(rng, unseen) if rng.random() < 0.8 else vocab.person(rng)
    doc.customer_street, doc.customer_city = vocab.address(rng)
    d = _random_date(rng)
    doc.issue_date = d
    doc.due_date = d + timedelta(days=rng.choice([7, 14, 14, 30, 30, 45])) if rng.random() < 0.7 else None
    if doc.due_date and doc.due_date > date(2026, 10, 10):
        doc.due_date = None
    doc.number = rng.choice([
        f"INV/{d:%Y}/{d:%m}/{rng.randint(1, 999):04d}",
        f"INV-{rng.randint(1, 9999):04d}",
        f"FK-{d:%Y}-{rng.randint(1, 9999):04d}",
        f"{rng.randint(1, 999):03d}/FAK/{d:%m}/{d:%Y}",
        f"INV{d:%y%m}{rng.randint(100, 999)}",
    ])  # fmt: skip
    category = rng.choice(["services", "services", "building", "electronics", "grocery"])
    doc.items = _items(rng, category, rng.choice([1, 2, 2, 3, 4, 5, 6]))
    _totals(doc, rng, p_discount=0.2, p_tax=0.8)
    doc.payment_method = "bank_transfer" if rng.random() < 0.35 else None
    doc.bank = vocab.bank_account(rng)
    doc.date_style = rng.choice([s for s in DATE_STYLES if s != "dmy_short"])
    doc.amount_style = rng.choice(["id", "id_dec", "rp_id", "rp_id_dec", "id_dash", "en"])
    doc.extra["signer"] = vocab.person(rng)
    return doc


def sample_other(doc_id: str, template: str, rng: random.Random, unseen: bool) -> SynthDoc:
    doc = SynthDoc(doc_id, "other", template, unseen, other_kind=template)
    doc.vendor_name = vocab.invoice_vendor(rng, unseen)
    doc.vendor_street, doc.vendor_city = vocab.address(rng)
    doc.vendor_phone = vocab.phone(rng)
    doc.issue_date = _random_date(rng)
    doc.date_style = rng.choice(["d_month_y", "dmy_slash", "day_d_month_y"])
    doc.amount_style = rng.choice(["id", "rp_id"])
    doc.customer = vocab.person(rng)
    doc.extra["people"] = [vocab.person(rng) for _ in range(8)]
    doc.extra["number"] = (
        f"{rng.randint(1, 300):03d}/{rng.choice(['SK', 'UND', 'PENG', 'SJ', 'NOT'])}/{doc.issue_date:%m}/{doc.issue_date:%Y}"
    )
    category = rng.choice(list(vocab.ITEMS))
    doc.items = _items(rng, category, rng.randint(4, 8))
    return doc
