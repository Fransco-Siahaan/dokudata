"""Business-rule validation of an extraction (PRD 7.3 and 9.3)."""

from __future__ import annotations

from datetime import date, timedelta
from typing import Any

from pipeline.config import rules_config
from pipeline.normalize import is_valid_npwp
from pipeline.schema import REQUIRED_FIELDS, Extraction, ValidationFinding


def _close(a: float, b: float, cfg: dict[str, Any]) -> bool:
    tol = max(cfg["amounts"]["tolerance_abs"], cfg["amounts"]["tolerance_rel"] * max(abs(a), abs(b)))
    return abs(a - b) <= tol


def _iso(value: Any) -> date | None:
    try:
        return date.fromisoformat(str(value))
    except (TypeError, ValueError):
        return None


def validate(
    ex: Extraction, today: date | None = None, cfg: dict[str, Any] | None = None
) -> list[ValidationFinding]:
    cfg = cfg or rules_config()
    today = today or date.today()
    out: list[ValidationFinding] = []

    def add(rule: str, status: str, fields: list[str], detail: str = "") -> None:
        out.append(ValidationFinding(rule=rule, status=status, fields=fields, detail=detail))  # type: ignore[arg-type]

    missing = [f for f in REQUIRED_FIELDS if not ex.field(f).present]
    if not ex.line_items:
        missing.append("line_items")
    add("required_fields_present", "fail" if missing else "pass", missing,
        f"Field wajib kosong: {', '.join(missing)}" if missing else "")  # fmt: skip

    total = ex.total.value
    subtotal = ex.subtotal.value
    discount = abs(ex.discount.value or 0.0)
    tax = ex.tax_amount.value or 0.0

    if total is None:
        add("total_positive", "fail", ["total"], "Total tidak ditemukan")
    elif total <= 0:
        add("total_positive", "fail", ["total"], f"Total harus lebih dari 0 (terbaca {total})")
    else:
        add("total_positive", "pass", ["total"])

    amounts = [li.amount for li in ex.line_items if li.amount is not None]
    if amounts:
        s = sum(amounts)
        if subtotal is not None:
            ok = _close(s, subtotal, cfg)
            add("sum_items_equals_subtotal", "pass" if ok else "warning", ["line_items", "subtotal"],
                "" if ok else f"Jumlah item {s:,.0f} berbeda dengan subtotal {subtotal:,.0f}")  # fmt: skip
        elif total is not None and not discount and not tax:
            ok = _close(s, total, cfg)
            add("sum_items_equals_subtotal", "pass" if ok else "warning", ["line_items", "total"],
                "" if ok else f"Jumlah item {s:,.0f} berbeda dengan total {total:,.0f}")  # fmt: skip
        else:
            add("sum_items_equals_subtotal", "skipped", ["line_items", "subtotal"], "Subtotal tidak tercetak")
    else:
        add("sum_items_equals_subtotal", "skipped", ["line_items"], "Tidak ada item")

    if subtotal is not None and total is not None:
        expected = subtotal - discount + tax
        ok = _close(expected, total, cfg)
        add("subtotal_plus_tax_equals_total", "pass" if ok else "warning", ["subtotal", "discount", "tax_amount", "total"],
            "" if ok else f"Subtotal - diskon + pajak = {expected:,.0f}, total tercetak {total:,.0f}")  # fmt: skip
    else:
        add("subtotal_plus_tax_equals_total", "skipped", ["subtotal", "total"])

    bad_rows = [
        i + 1
        for i, li in enumerate(ex.line_items)
        if li.qty is not None and li.unit_price is not None and li.amount is not None
        and not _close(li.qty * li.unit_price, li.amount, cfg)
    ]  # fmt: skip
    checked = sum(
        1
        for li in ex.line_items
        if li.qty is not None and li.unit_price is not None and li.amount is not None
    )
    if checked:
        add("line_qty_times_price", "warning" if bad_rows else "pass", ["line_items"],
            f"Qty x harga tidak sama dengan jumlah pada baris {bad_rows}" if bad_rows else "")  # fmt: skip
    else:
        add("line_qty_times_price", "skipped", ["line_items"])

    issue = _iso(ex.issue_date.value)
    if issue is None:
        add("issue_date_valid", "fail", ["issue_date"], "Tanggal dokumen tidak valid atau kosong")
    elif issue > today + timedelta(days=cfg["dates"]["max_future_days"]):
        add("issue_date_valid", "fail", ["issue_date"], f"Tanggal {issue.isoformat()} berada di masa depan")
    elif issue.year < cfg["dates"]["min_year"]:
        add("issue_date_valid", "warning", ["issue_date"], f"Tanggal {issue.isoformat()} tidak wajar")
    else:
        add("issue_date_valid", "pass", ["issue_date"])

    due = _iso(ex.due_date.value)
    if due is not None and issue is not None:
        ok = due >= issue
        add("due_date_after_issue", "pass" if ok else "warning", ["due_date", "issue_date"],
            "" if ok else "Jatuh tempo lebih awal dari tanggal dokumen")  # fmt: skip

    if ex.vendor_tax_id.present:
        ok = is_valid_npwp(str(ex.vendor_tax_id.value))
        add("vendor_tax_id_format", "pass" if ok else "warning", ["vendor_tax_id"],
            "" if ok else "NPWP harus 15 atau 16 digit")  # fmt: skip

    if ex.tax_amount.present and subtotal is not None:
        base = subtotal - discount
        if base > 0:
            rate = float(ex.tax_amount.value) / base
            rates = cfg["tax"]["vat_rates"]
            ok = any(abs(rate - r) <= cfg["tax"]["rate_tolerance"] for r in rates)
            add("tax_rate_matches_config", "pass" if ok else "warning", ["tax_amount"],
                "" if ok else f"Tarif pajak {rate:.2%} tidak sesuai konfigurasi {[f'{r:.0%}' for r in rates]}")  # fmt: skip
    return out
