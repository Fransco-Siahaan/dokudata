"""HTML/CSS templates rendered to PDF by PyMuPDF's Story engine.

A template receives a :class:`SynthDoc` and returns ``(html, css, page)``.
Templates must print every field that is set on the document; when a layout
has no place for a field it clears it, so ground truth always equals what is
visible on the page.

Held-out templates (``HELD_OUT``) appear only in ``test_unseen``.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass
from html import escape as e

from ml.synthetic.model import SynthDoc, fmt_date, terbilang
from ml.synthetic.vocab import format_npwp

MM = 72 / 25.4


@dataclass
class Page:
    width: float
    height: float | None  # None = trim to content (receipts)
    margin: float = 8.0


Template = Callable[[SynthDoc, random.Random], tuple[str, str, Page]]

FONTS = {"mono": "monospace", "sans": "sans-serif", "serif": "serif"}


def _row(left: str, right: str, bold: bool = False, size: str = "") -> str:
    style = "font-weight:bold;" if bold else ""
    style += f"font-size:{size};" if size else ""
    return (f'<tr style="{style}"><td style="width:62%">{left}</td>'
            f'<td style="width:38%;text-align:right">{right}</td></tr>')  # fmt: skip


def _sep(char: str = "-", n: int = 38) -> str:
    return f'<div style="text-align:center">{char * n}</div>'


def _narrow_safe(doc: SynthDoc, rng: random.Random, width_mm: int) -> float:
    """58 mm printers fit ~32 characters, so they print short amounts (no "Rp", no ",00")."""
    if width_mm == 58 and doc.amount_style not in ("id", "en", "plain"):
        doc.amount_style = rng.choice(["id", "en", "plain"])
    return width_mm * MM


def _injection(doc: SynthDoc) -> str:
    return f'<div style="font-size:6pt;color:#555">{e(doc.injection)}</div>' if doc.injection else ""


def _totals_rows(doc: SynthDoc, labels: dict[str, str], force_sub: bool = False) -> str:
    rows = []
    show_sub = force_sub or bool(doc.discount or doc.tax_amount)
    doc.extra["show_subtotal"] = show_sub
    if show_sub:
        rows.append(_row(labels.get("subtotal", "SUBTOTAL"), doc.amt(doc.subtotal)))
    if doc.discount:
        rows.append(_row(labels.get("discount", "DISKON"), doc.amt(-doc.discount)))
    if doc.tax_amount:
        pct = f"{round(doc.tax_rate * 100)}%"
        rows.append(_row(labels.get("tax", "PPN {pct}").format(pct=pct), doc.amt(doc.tax_amount)))
    rows.append(
        _row(
            labels.get("total", "TOTAL"),
            doc.amt(doc.total, force_rp=labels.get("rp_total") == "1"),
            bold=True,
        )
    )
    return "".join(rows)


def _payment_rows(doc: SynthDoc, cash_label: str = "TUNAI", change_label: str = "KEMBALI") -> str:
    rows = []
    if doc.payment_method == "cash" and doc.cash_paid is not None:
        rows.append(_row(cash_label, doc.amt(doc.cash_paid)))
        rows.append(_row(change_label, doc.amt(doc.change or 0)))
    elif doc.payment_display:
        rows.append(_row(doc.payment_display, doc.amt(doc.total)))
    return "".join(rows)


# --------------------------------------------------------------------------- receipts


def r_thermal_mono(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    width = _narrow_safe(doc, rng, rng.choice([58, 80]))
    h = [f'<div style="text-align:center;font-weight:bold;font-size:11pt">{e(doc.vendor_name.upper())}</div>',
         f'<div style="text-align:center">{e(doc.vendor_street)}<br/>{e(doc.vendor_city)}<br/>Telp. {e(doc.vendor_phone)}</div>']  # fmt: skip
    if doc.vendor_npwp:
        h.append(f'<div style="text-align:center">NPWP: {format_npwp(doc.vendor_npwp)}</div>')
    h.append(_sep())
    meta = f'<table style="width:100%">{_row(f"No: {e(doc.number)}" if doc.number else "", doc.dt(doc.issue_date))}'
    meta += _row(f"Kasir: {e(doc.cashier)}", doc.time_str) + "</table>"
    h.append(meta)
    h.append(_sep())
    items = "".join(
        f'<tr><td colspan="2">{e(it.description)}</td></tr>'
        + _row(f"&nbsp;&nbsp;{it.qty} x {doc.amt(it.unit_price)}", doc.amt(it.amount))
        for it in doc.items
    )
    h.append(f'<table style="width:100%">{items}</table>')
    h.append(_sep())
    h.append(f'<table style="width:100%">{_totals_rows(doc, {})}{_payment_rows(doc)}</table>')
    h.append(_sep())
    h.append(_injection(doc))
    h.append(
        '<div style="text-align:center">Terima kasih atas kunjungan Anda<br/>Barang yang sudah dibeli tidak dapat ditukar</div>'
    )
    css = f"body {{font-family: monospace; font-size: {rng.choice(['7pt', '7.5pt', '8pt'])};}}"
    return "".join(h), css, Page(width, None)


def r_thermal_table(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    width = 80 * MM
    h = [f'<div style="text-align:center;font-weight:bold;font-size:12pt">{e(doc.vendor_name)}</div>',
         f'<div style="text-align:center;font-size:7pt">{e(doc.vendor_street)}, {e(doc.vendor_city)}</div>']  # fmt: skip
    if doc.vendor_npwp:
        h.append(f'<div style="text-align:center;font-size:7pt">NPWP {format_npwp(doc.vendor_npwp)}</div>')
    h.append('<div style="border-bottom:1px solid black;margin:3px 0"> </div>')
    h.append(f"<div>Tanggal: {doc.dt(doc.issue_date)} {doc.time_str}</div>")
    if doc.number:
        h.append(f"<div>No. Struk: {e(doc.number)}</div>")
    rows = "".join(
        f'<tr><td style="width:58%">{e(it.description)}</td><td style="width:10%;text-align:center">{it.qty}</td>'
        f'<td style="width:32%;text-align:right">{doc.amt(it.amount)}</td></tr>'
        for it in doc.items
    )
    h.append('<div style="border-bottom:1px solid black;margin:3px 0"> </div>')
    h.append(f'<table style="width:100%">{rows}</table>')
    h.append('<div style="border-bottom:1px solid black;margin:3px 0"> </div>')
    labels = {"subtotal": "Subtotal", "discount": "Diskon", "tax": "PPN ({pct})", "total": "Total"}
    h.append(
        f'<table style="width:100%">{_totals_rows(doc, labels)}{_payment_rows(doc, "Tunai", "Kembali")}</table>'
    )
    h.append(_injection(doc))
    h.append('<div style="text-align:center;margin-top:4px">-- Terima Kasih --</div>')
    return (
        "".join(h),
        f"body {{font-family: sans-serif; font-size: {rng.choice(['7pt', '8pt'])};}}",
        Page(width, None),
    )


def r_minimarket(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    width = 80 * MM
    h = [f'<div style="text-align:center;font-weight:bold;font-size:10pt">{e(doc.vendor_name.upper())}</div>',
         f'<div style="text-align:center">{e(doc.vendor_street)}</div>',
         f'<div style="text-align:center">{e(doc.vendor_city.upper())}</div>']  # fmt: skip
    if doc.vendor_npwp:
        h.append(f'<div style="text-align:center">NPWP : {format_npwp(doc.vendor_npwp)}</div>')
    meta = f"{doc.dt(doc.issue_date)}-{doc.time_str}"
    if doc.number:
        meta += f" / {e(doc.number)}"
    h.append(f"<div>{meta}</div><div>KSR: {e(doc.cashier.upper())}</div>")
    h.append(_sep("="))
    if doc.amount_style not in ("id", "en", "plain"):
        doc.amount_style = rng.choice(["id", "en", "plain"])
    for it in doc.items:
        # Retail POS systems print a truncated item name; ground truth is what is printed.
        it.description = it.description.upper()[:15].rstrip()
    head = ('<tr style="font-weight:bold"><td style="width:46%">ITEM</td><td style="width:8%;text-align:right">QTY</td>'
            '<td style="width:22%;text-align:right">HARGA</td><td style="width:24%;text-align:right">JUMLAH</td></tr>')  # fmt: skip
    rows = "".join(
        f'<tr><td>{e(it.description.upper())}</td><td style="text-align:right">{it.qty}</td>'
        f'<td style="text-align:right">{doc.amt(it.unit_price)}</td><td style="text-align:right">{doc.amt(it.amount)}</td></tr>'
        for it in doc.items
    )
    h.append(f'<table style="width:100%">{head}{rows}</table>')
    h.append(_sep("="))
    labels = {"subtotal": "TOTAL ITEM", "discount": rng.choice(["HEMAT", "POTONGAN", "DISKON"]),
              "tax": "PPN {pct}", "total": "TOTAL BELANJA"}  # fmt: skip
    h.append(f'<table style="width:100%">{_row(f"JML ITEM : {sum(i.qty for i in doc.items)}", "")}'
             f'{_totals_rows(doc, labels, force_sub=True)}{_payment_rows(doc)}</table>')  # fmt: skip
    h.append(_injection(doc))
    h.append('<div style="text-align:center">LAYANAN KONSUMEN<br/>SMS/WA 0812-0000-1234</div>')
    return "".join(h), "body {font-family: monospace; font-size: 7pt;}", Page(width, None)


def r_restaurant(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    width = 80 * MM
    h = [f'<div style="text-align:center;font-size:13pt;font-weight:bold;font-family:serif">{e(doc.vendor_name)}</div>',
         f'<div style="text-align:center;font-size:7pt">{e(doc.vendor_street)} - {e(doc.vendor_city)}<br/>{e(doc.vendor_phone)}</div>']  # fmt: skip
    if doc.vendor_npwp:
        h.append(f'<div style="text-align:center;font-size:7pt">NPWP: {format_npwp(doc.vendor_npwp)}</div>')
    h.append(_sep("-", 44))
    h.append(f'<table style="width:100%">{_row(f"Meja {rng.randint(1, 30):02d}", doc.dt(doc.issue_date))}'
             f'{_row("Pelayan: " + e(doc.cashier), doc.time_str)}</table>')  # fmt: skip
    if doc.number:
        h.append(f"<div>Bill #{e(doc.number)}</div>")
    h.append(_sep("-", 44))
    rows = "".join(
        f'<tr><td style="width:10%">{it.qty}</td><td style="width:56%">{e(it.description)}</td>'
        f'<td style="width:34%;text-align:right">{doc.amt(it.amount)}</td></tr>'
        for it in doc.items
    )
    h.append(f'<table style="width:100%">{rows}</table>')
    h.append(_sep("-", 44))
    labels = {"subtotal": "Sub Total", "discount": "Diskon", "tax": "PPN {pct}", "total": "Grand Total"}
    h.append(
        f'<table style="width:100%">{_totals_rows(doc, labels)}{_payment_rows(doc, "Bayar", "Kembali")}</table>'
    )
    h.append(_injection(doc))
    h.append('<div style="text-align:center;font-style:italic">Selamat menikmati!</div>')
    return "".join(h), "body {font-family: sans-serif; font-size: 8pt;}", Page(width, None)


def r_nota_kontan(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    width = 148 * MM
    customer = rng.choice(["Bapak ", "Ibu ", ""]) + rng.choice(
        ["Hendra", "Siti", "Rudi", "Lina", "Toko Sumber Air"]
    )
    doc.payment_method = doc.payment_display = None  # this layout has no payment row
    doc.cash_paid = doc.change = None
    h = ['<table style="width:100%"><tr>'
         f'<td style="width:60%"><b style="font-size:13pt">{e(doc.vendor_name)}</b><br/>{e(doc.vendor_street)}<br/>'
         f'{e(doc.vendor_city)} - Telp. {e(doc.vendor_phone)}'
         + (f"<br/>NPWP {format_npwp(doc.vendor_npwp)}" if doc.vendor_npwp else "")
         + f'</td><td style="width:40%">{e(doc.vendor_city)}, {doc.dt(doc.issue_date)}<br/>Kepada Yth.<br/>{e(customer)}</td>'
         "</tr></table>"]  # fmt: skip
    title = "NOTA" + (f" No. {e(doc.number)}" if doc.number else "")
    h.append(f'<div style="font-size:12pt;font-weight:bold;border-bottom:1px solid black">{title}</div>')
    head = ('<tr style="font-weight:bold;background-color:#eeeeee"><td style="width:14%">Banyaknya</td>'
            '<td style="width:44%">Nama Barang</td><td style="width:20%;text-align:right">Harga</td>'
            '<td style="width:22%;text-align:right">Jumlah</td></tr>')  # fmt: skip
    rows = "".join(
        f'<tr><td>{it.qty}</td><td>{e(it.description)}</td><td style="text-align:right">{doc.amt(it.unit_price)}</td>'
        f'<td style="text-align:right">{doc.amt(it.amount)}</td></tr>'
        for it in doc.items
    )
    h.append(f'<table style="width:100%">{head}{rows}</table>')
    labels = {
        "subtotal": "Jumlah",
        "discount": "Potongan",
        "tax": "PPN {pct}",
        "total": "Jumlah Rp",
        "rp_total": "1",
    }
    h.append(f'<table style="width:100%">{_totals_rows(doc, labels)}</table>')
    h.append(_injection(doc))
    h.append('<table style="width:100%;margin-top:14px"><tr><td style="width:50%;text-align:center">Tanda Terima<br/><br/><br/>(..........)</td>'
             '<td style="width:50%;text-align:center">Hormat Kami<br/><br/><br/>(..........)</td></tr></table>')  # fmt: skip
    return "".join(h), "body {font-family: serif; font-size: 9pt;}", Page(width, None, 14)


def r_apotek(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    width = 80 * MM
    h = [f'<div style="text-align:center;font-weight:bold;font-size:11pt">{e(doc.vendor_name.upper())}</div>',
         f'<div style="text-align:center;font-size:7pt">{e(doc.vendor_street)}, {e(doc.vendor_city)}<br/>Telp {e(doc.vendor_phone)}</div>',
         f'<div style="text-align:center;font-size:7pt">Apoteker: {e(doc.cashier)} {rng.choice(["Halim", "Susanto", "Permana"])}, S.Farm</div>']  # fmt: skip
    if doc.vendor_npwp:
        h.append(f'<div style="text-align:center;font-size:7pt">NPWP {format_npwp(doc.vendor_npwp)}</div>')
    h.append(_sep("-", 40))
    if doc.number:
        h.append(f"<div>No. Transaksi : {e(doc.number)}</div>")
    h.append(f"<div>Tgl : {doc.dt(doc.issue_date)} Jam {doc.time_str}</div>")
    h.append(_sep("-", 40))
    rows = "".join(
        f'<tr><td colspan="2">{e(it.description)}</td></tr>'
        + _row(f"{it.qty} @ {doc.amt(it.unit_price)}", doc.amt(it.amount))
        for it in doc.items
    )
    h.append(f'<table style="width:100%">{rows}</table>')
    h.append(_sep("-", 40))
    labels = {"subtotal": "Subtotal", "discount": "Diskon", "tax": "PPN {pct}", "total": "Total"}
    h.append(
        f'<table style="width:100%">{_totals_rows(doc, labels)}{_payment_rows(doc, "Bayar", "Kembali")}</table>'
    )
    h.append(_injection(doc))
    h.append('<div style="text-align:center;font-size:7pt">Semoga lekas sembuh</div>')
    return "".join(h), "body {font-family: sans-serif; font-size: 7.5pt;}", Page(width, None)


def r_digital(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    width = 80 * MM
    if doc.payment_method in (None, "cash"):
        doc.payment_method = rng.choice(["qris", "e_wallet", "debit_card"])
        doc.payment_display = {
            "qris": "QRIS",
            "e_wallet": rng.choice(["GOPAY", "OVO", "DANA"]),
            "debit_card": "DEBIT BCA",
        }[doc.payment_method]
        doc.cash_paid = doc.change = None
    h = ['<div style="text-align:center;font-weight:bold;font-size:10pt">BUKTI PEMBAYARAN</div>',
         '<div style="text-align:center;color:#2a7a2a">Transaksi Berhasil</div>', _sep("-", 40),
         '<table style="width:100%">',
         _row("Merchant", e(doc.vendor_name)),
         _row("Lokasi", e(doc.vendor_city))]  # fmt: skip
    if doc.vendor_npwp:
        h.append(_row("NPWP", format_npwp(doc.vendor_npwp)))
    if doc.number:
        h.append(_row("ID Transaksi", e(doc.number)))
    h.append(_row("Waktu", f"{doc.dt(doc.issue_date)} {doc.time_str}"))
    h.append(_row("Metode", e(doc.payment_display or "")))
    h.append("</table>")
    h.append(_sep("-", 40))
    rows = "".join(_row(f"{e(it.description)} x{it.qty}", doc.amt(it.amount)) for it in doc.items)
    h.append(f'<table style="width:100%">{rows}</table>')
    h.append(_sep("-", 40))
    labels = {
        "subtotal": "Subtotal",
        "discount": "Promo",
        "tax": "PPN {pct}",
        "total": "Total Pembayaran",
        "rp_total": "1",
    }
    h.append(f'<table style="width:100%">{_totals_rows(doc, labels)}</table>')
    h.append(_injection(doc))
    h.append(
        '<div style="text-align:center;font-size:6.5pt">Simpan bukti ini sebagai tanda pembayaran yang sah</div>'
    )
    return "".join(h), "body {font-family: sans-serif; font-size: 7.5pt;}", Page(width, None)


def r_heldout_compact(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    """Held-out receipt layout: qty in parentheses, dotted leaders, TOTAL BAYAR wording."""
    width = _narrow_safe(doc, rng, rng.choice([58, 80]))
    h = [f'<div style="text-align:center;font-weight:bold">*** {e(doc.vendor_name.upper())} ***</div>',
         f'<div style="text-align:center;font-size:6.5pt">{e(doc.vendor_street)} {e(doc.vendor_city)}</div>']  # fmt: skip
    if doc.vendor_npwp:
        h.append(
            f'<div style="text-align:center;font-size:6.5pt">N.P.W.P {format_npwp(doc.vendor_npwp)}</div>'
        )
    h.append(
        f"<div>{doc.dt(doc.issue_date)} {doc.time_str}"
        + (f" #{e(doc.number)}" if doc.number else "")
        + "</div>"
    )
    h.append(_sep(".", 36))
    rows = "".join(_row(f"{e(it.description)} ({it.qty})", doc.amt(it.amount)) for it in doc.items)
    h.append(f'<table style="width:100%">{rows}</table>')
    h.append(_sep(".", 36))
    labels = {"subtotal": "TOTAL HARGA", "discount": "DISC", "tax": "PAJAK PPN {pct}", "total": "TOTAL BAYAR"}
    h.append(
        f'<table style="width:100%">{_totals_rows(doc, labels)}{_payment_rows(doc, "UANG", "KEMBALIAN")}</table>'
    )
    h.append(_injection(doc))
    h.append('<div style="text-align:center">~ Terima kasih ~</div>')
    return "".join(h), "body {font-family: monospace; font-size: 7pt;}", Page(width, None)


# --------------------------------------------------------------------------- invoices

A4 = Page(595, 842, 40)


def _items_table(
    doc: SynthDoc, head_bg: str = "#e5e7eb", stripe: str | None = None, labels: tuple[str, ...] = ()
) -> str:
    lb = labels or ("No", "Deskripsi", "Qty", "Harga Satuan", "Jumlah")
    head = (f'<tr style="font-weight:bold;background-color:{head_bg}"><td style="width:6%">{lb[0]}</td>'
            f'<td style="width:46%">{lb[1]}</td><td style="width:8%;text-align:right">{lb[2]}</td>'
            f'<td style="width:20%;text-align:right">{lb[3]}</td><td style="width:20%;text-align:right">{lb[4]}</td></tr>')  # fmt: skip
    rows = []
    for i, it in enumerate(doc.items, 1):
        bg = f"background-color:{stripe};" if stripe and i % 2 == 0 else ""
        rows.append(
            f'<tr style="{bg}"><td>{i}</td><td>{e(it.description)}</td><td style="text-align:right">{it.qty}</td>'
            f'<td style="text-align:right">{doc.amt(it.unit_price)}</td><td style="text-align:right">{doc.amt(it.amount)}</td></tr>'
        )
    return f'<table style="width:100%">{head}{"".join(rows)}</table>'


def _inv_totals(doc: SynthDoc, labels: dict[str, str]) -> str:
    doc.extra["show_subtotal"] = True
    rows = [("subtotal", "Subtotal", doc.amt(doc.subtotal))]
    if doc.discount:
        rows.append(("discount", "Diskon", doc.amt(-doc.discount)))
    if doc.tax_amount:
        rows.append(("tax", "PPN {pct}", doc.amt(doc.tax_amount)))
    rows.append(("total", "Total", doc.amt(doc.total, force_rp=True)))
    pct = f"{round(doc.tax_rate * 100)}%"
    out = []
    for key, default, value in rows:
        label = labels.get(key, default).format(pct=pct)
        bold = "font-weight:bold;" if key == "total" else ""
        out.append(f'<tr style="{bold}"><td style="width:55%"></td><td style="width:25%">{label}</td>'
                   f'<td style="width:20%;text-align:right">{value}</td></tr>')  # fmt: skip
    return f'<table style="width:100%">{"".join(out)}</table>'


def _bank_block(doc: SynthDoc) -> str:
    if doc.payment_method == "bank_transfer":
        return f'<div style="margin-top:10px">Pembayaran melalui transfer ke rekening {e(doc.bank)} a.n. {e(doc.vendor_name)}</div>'
    return f'<div style="margin-top:10px">Rekening: {e(doc.bank)} a.n. {e(doc.vendor_name)}</div>'


def _signature(doc: SynthDoc, title: str = "Hormat kami") -> str:
    return (f'<table style="width:100%;margin-top:24px"><tr><td style="width:60%"></td><td style="width:40%;text-align:center">'
            f'{e(doc.vendor_city)}, {doc.dt(doc.issue_date)}<br/>{title}<br/><br/><br/><br/>{e(doc.extra["signer"])}</td></tr></table>')  # fmt: skip


def i_classic(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    npwp = f"<br/>NPWP: {format_npwp(doc.vendor_npwp)}" if doc.vendor_npwp else ""
    meta = f"No. Invoice: {e(doc.number or '')}<br/>Tanggal: {doc.dt(doc.issue_date)}"
    if doc.due_date:
        meta += f"<br/>Jatuh Tempo: {doc.dt(doc.due_date)}"
    h = ['<table style="width:100%"><tr>'
         f'<td style="width:60%"><b style="font-size:15pt">{e(doc.vendor_name)}</b><br/>{e(doc.vendor_street)}<br/>'
         f'{e(doc.vendor_city)}<br/>Telp. {e(doc.vendor_phone)}{npwp}</td>'
         f'<td style="width:40%;text-align:right"><b style="font-size:22pt;color:#374151">INVOICE</b><br/>{meta}</td></tr></table>',
         f'<div style="margin-top:14px"><b>Tagihan kepada:</b><br/>{e(doc.customer or "")}<br/>{e(doc.customer_street)}, {e(doc.customer_city)}</div>',
         '<div style="margin-top:12px"></div>', _items_table(doc), _inv_totals(doc, {}), _bank_block(doc),
         _injection(doc), _signature(doc)]  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 9.5pt;}", A4


def i_faktur_penjualan(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    npwp = f" | NPWP {format_npwp(doc.vendor_npwp)}" if doc.vendor_npwp else ""
    meta = f"No. Faktur : {e(doc.number or '')}<br/>Tanggal : {doc.dt(doc.issue_date)}"
    if doc.due_date:
        meta += f"<br/>Jatuh Tempo : {doc.dt(doc.due_date)}"
    h = [f'<div style="text-align:center;font-size:16pt;font-weight:bold">{e(doc.vendor_name.upper())}</div>',
         f'<div style="text-align:center">{e(doc.vendor_street)}, {e(doc.vendor_city)} | Telp. {e(doc.vendor_phone)}{npwp}</div>',
         '<div style="border-bottom:2px solid black;margin:6px 0"> </div>',
         '<div style="text-align:center;font-size:13pt;font-weight:bold;margin:8px 0">FAKTUR PENJUALAN</div>',
         f'<table style="width:100%"><tr><td style="width:55%">Kepada Yth.<br/><b>{e(doc.customer or "")}</b><br/>'
         f'{e(doc.customer_street)}<br/>{e(doc.customer_city)}</td><td style="width:45%">{meta}</td></tr></table>',
         '<div style="margin-top:10px"></div>',
         _items_table(doc, "#d1d5db", labels=("No", "Nama Barang / Jasa", "Qty", "Harga", "Jumlah")),
         _inv_totals(doc, {"subtotal": "Jumlah", "discount": "Potongan", "total": "Total Tagihan"}),
         f'<div style="font-style:italic;margin-top:6px">Terbilang: {terbilang(doc.total)} rupiah</div>',
         _bank_block(doc), _injection(doc), _signature(doc)]  # fmt: skip
    return "".join(h), f"body {{font-family: {rng.choice(['serif', 'sans-serif'])}; font-size: 9.5pt;}}", A4


def i_modern(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    color = rng.choice(["#1e3a5f", "#0f766e", "#7c2d12", "#4c1d95", "#111827"])
    npwp = f" &middot; NPWP {format_npwp(doc.vendor_npwp)}" if doc.vendor_npwp else ""
    due = f"<br/>Jatuh tempo {doc.dt(doc.due_date)}" if doc.due_date else ""
    h = [f'<div style="background-color:{color};color:white;padding:10px"><b style="font-size:16pt">{e(doc.vendor_name)}</b><br/>'
         f'{e(doc.vendor_street)}, {e(doc.vendor_city)}{npwp}</div>',
         f'<table style="width:100%;margin-top:14px"><tr><td style="width:50%"><span style="color:#6b7280">DITAGIHKAN KE</span><br/>'
         f'<b>{e(doc.customer or "")}</b><br/>{e(doc.customer_city)}</td>'
         f'<td style="width:50%;text-align:right"><b style="font-size:14pt;color:{color}">Invoice #{e(doc.number or "")}</b><br/>'
         f'Diterbitkan {doc.dt(doc.issue_date)}{due}</td></tr></table>',
         '<div style="margin-top:12px"></div>', _items_table(doc, "#f3f4f6", stripe="#f9fafb"),
         _inv_totals(doc, {"total": "Grand Total"}), _bank_block(doc), _injection(doc),
         f'<div style="margin-top:18px;color:#6b7280;font-size:8pt">Terima kasih atas kepercayaan Anda. Hubungi {e(doc.vendor_phone)} untuk pertanyaan.</div>']  # fmt: skip
    doc.extra["signer"] = doc.extra.get("signer", "")
    return "".join(h), "body {font-family: sans-serif; font-size: 9.5pt;}", A4


def i_service(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    npwp = f"NPWP: {format_npwp(doc.vendor_npwp)}<br/>" if doc.vendor_npwp else ""
    h = ['<table style="width:100%"><tr>'
         f'<td style="width:50%"><b style="font-size:20pt">TAGIHAN JASA</b></td>'
         f'<td style="width:50%;text-align:right"><b>{e(doc.vendor_name)}</b><br/>{e(doc.vendor_street)}<br/>{e(doc.vendor_city)}<br/>{npwp}{e(doc.vendor_phone)}</td>'
         '</tr></table>',
         f'<div style="margin-top:12px">Nomor: {e(doc.number or "")}<br/>Tanggal: {doc.dt(doc.issue_date)}'
         + (f"<br/>Termin: {(doc.due_date - doc.issue_date).days} hari (jatuh tempo {doc.dt(doc.due_date)})" if doc.due_date and doc.issue_date else "")
         + "</div>",
         f'<div style="margin-top:8px">Klien: <b>{e(doc.customer or "")}</b></div>',
         '<div style="margin-top:10px"></div>',
         _items_table(doc, "#fde68a", labels=("#", "Uraian Pekerjaan", "Unit", "Tarif", "Biaya")),
         _inv_totals(doc, {"subtotal": "Total Biaya", "total": "Jumlah Dibayar"}), _bank_block(doc), _injection(doc),
         _signature(doc, "Penyedia Jasa")]  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 9pt;}", A4


def i_meta_table(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    cell = 'style="background-color:#f3f4f6;width:22%"'
    rows = [f"<tr><td {cell}>Nomor Invoice</td><td style=\"width:28%\">{e(doc.number or '')}</td>"
            f"<td {cell}>Tanggal Invoice</td><td style=\"width:28%\">{doc.dt(doc.issue_date)}</td></tr>"]  # fmt: skip
    rows.append(f"<tr><td {cell}>NPWP Penjual</td><td>{format_npwp(doc.vendor_npwp) if doc.vendor_npwp else '-'}</td>"
                f"<td {cell}>Jatuh Tempo</td><td>{doc.dt(doc.due_date) if doc.due_date else '-'}</td></tr>")  # fmt: skip
    h = [f'<div style="font-size:15pt;font-weight:bold">{e(doc.vendor_name)}</div>',
         f'<div>{e(doc.vendor_street)}, {e(doc.vendor_city)} &middot; {e(doc.vendor_phone)}</div>',
         '<div style="text-align:right;font-size:18pt;font-weight:bold;margin:8px 0">INVOICE</div>',
         f'<table style="width:100%">{"".join(rows)}</table>',
         f'<div style="margin-top:10px">Pembeli: <b>{e(doc.customer or "")}</b>, {e(doc.customer_city)}</div>',
         '<div style="margin-top:10px"></div>', _items_table(doc, "#e5e7eb"),
         _inv_totals(doc, {"subtotal": "Sub Total", "discount": "Diskon", "total": "JUMLAH TAGIHAN"}),
         _bank_block(doc), _injection(doc), _signature(doc)]  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 9pt;}", A4


def i_heldout_english(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    """Held-out invoice layout: English labels and month-first dates."""
    doc.date_style = "en_mon"
    npwp = f"<br/>Tax ID (NPWP): {format_npwp(doc.vendor_npwp)}" if doc.vendor_npwp else ""
    due = f"<br/>Due Date: {fmt_date(doc.due_date, 'en_mon')}" if doc.due_date else ""
    h = ['<div style="text-align:right;font-size:20pt;font-weight:bold;color:#1f2937">TAX INVOICE</div>',
         f'<table style="width:100%"><tr><td style="width:55%"><b>{e(doc.vendor_name)}</b><br/>{e(doc.vendor_street)}<br/>'
         f'{e(doc.vendor_city)}, Indonesia{npwp}</td><td style="width:45%">Invoice No.: {e(doc.number or "")}<br/>'
         f'Invoice Date: {fmt_date(doc.issue_date, "en_mon") if doc.issue_date else ""}{due}</td></tr></table>',
         f'<div style="margin-top:12px"><b>Bill To:</b> {e(doc.customer or "")}, {e(doc.customer_city)}</div>',
         '<div style="margin-top:10px"></div>',
         _items_table(doc, "#e5e7eb", labels=("#", "Description", "Qty", "Unit Price", "Amount")),
         _inv_totals(doc, {"subtotal": "Subtotal", "discount": "Discount", "tax": "VAT {pct}", "total": "Amount Due"}),
         f'<div style="margin-top:10px">Please transfer to {e(doc.bank)}.</div>' if doc.payment_method == "bank_transfer"
         else f'<div style="margin-top:10px">Bank: {e(doc.bank)}</div>',
         _injection(doc)]  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 9.5pt;}", A4


# --------------------------------------------------------------------------- other documents


def _kop(doc: SynthDoc) -> str:
    return (f'<div style="text-align:center;font-size:14pt;font-weight:bold">{e(doc.vendor_name.upper())}</div>'
            f'<div style="text-align:center">{e(doc.vendor_street)}, {e(doc.vendor_city)} - Telp. {e(doc.vendor_phone)}</div>'
            '<div style="border-bottom:2px solid black;margin:6px 0 12px 0"> </div>')  # fmt: skip


def o_undangan(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    h = [_kop(doc),
         f'<table style="width:100%"><tr><td style="width:60%">Nomor: {doc.extra["number"]}<br/>Lampiran: -<br/>Perihal: <b>Undangan Rapat</b></td>'
         f'<td style="width:40%;text-align:right">{e(doc.vendor_city)}, {doc.dt(doc.issue_date)}</td></tr></table>',
         f'<p>Kepada Yth.<br/>Bapak/Ibu {e(doc.customer or "")}<br/>di tempat</p>',
         "<p>Dengan hormat,<br/>Bersama surat ini kami mengundang Bapak/Ibu untuk menghadiri rapat koordinasi yang akan dilaksanakan pada:</p>",
         f'<table><tr><td style="width:30%">Hari/Tanggal</td><td>: {fmt_date(doc.issue_date, "day_d_month_y") if doc.issue_date else ""}</td></tr>'
         f'<tr><td>Waktu</td><td>: {rng.randint(8, 14):02d}.00 WIB s.d. selesai</td></tr><tr><td>Tempat</td><td>: Ruang Rapat Lt. {rng.randint(1, 5)}</td></tr>'
         "<tr><td>Acara</td><td>: Evaluasi kinerja triwulan dan rencana anggaran</td></tr></table>",
         "<p>Mengingat pentingnya acara tersebut, kami mohon kehadiran Bapak/Ibu tepat waktu. Atas perhatiannya kami ucapkan terima kasih.</p>",
         f'<p style="text-align:right">Hormat kami,<br/><br/><br/>{e(doc.extra["people"][0])}<br/>Sekretaris</p>']  # fmt: skip
    return "".join(h), f"body {{font-family: {rng.choice(['serif', 'sans-serif'])}; font-size: 10pt;}}", A4


def o_surat_keterangan(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    p = doc.extra["people"]
    h = [_kop(doc), '<div style="text-align:center;font-weight:bold;text-decoration:underline">SURAT KETERANGAN KERJA</div>',
         f'<div style="text-align:center">Nomor: {doc.extra["number"]}</div>',
         f"<p>Yang bertanda tangan di bawah ini, {e(p[0])}, selaku Manajer Personalia {e(doc.vendor_name)}, menerangkan bahwa:</p>",
         f'<table><tr><td style="width:30%">Nama</td><td>: {e(p[1])}</td></tr><tr><td>Jabatan</td><td>: {rng.choice(["Staf Administrasi", "Akuntan", "Teknisi", "Staf Gudang"])}</td></tr>'
         f'<tr><td>Mulai bekerja</td><td>: {fmt_date(doc.issue_date.replace(year=doc.issue_date.year - rng.randint(1, 8)), "d_month_y") if doc.issue_date else ""}</td></tr></table>',
         "<p>adalah benar karyawan tetap perusahaan kami dan selama bekerja menunjukkan dedikasi yang baik. "
         "Surat keterangan ini dibuat untuk dipergunakan sebagaimana mestinya.</p>",
         f'<p style="text-align:right">{e(doc.vendor_city)}, {doc.dt(doc.issue_date)}<br/><br/><br/>{e(p[0])}</p>']  # fmt: skip
    return "".join(h), "body {font-family: serif; font-size: 10.5pt;}", A4


def o_pengumuman(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    h = [_kop(doc), '<div style="text-align:center;font-size:16pt;font-weight:bold">PENGUMUMAN</div>',
         f'<div style="text-align:center">No. {doc.extra["number"]}</div>',
         "<p>Diberitahukan kepada seluruh karyawan bahwa sehubungan dengan kegiatan pemeliharaan gedung, "
         f"operasional kantor pada {doc.dt(doc.issue_date)} akan dimulai pukul {rng.randint(9, 11)}.00 WIB.</p>",
         "<ol><li>Area parkir basement ditutup sementara.</li><li>Lift barang tidak dapat digunakan.</li>"
         "<li>Mohon menyimpan dokumen penting di lemari terkunci.</li></ol>",
         "<p>Demikian pengumuman ini disampaikan. Atas perhatian dan kerja samanya kami ucapkan terima kasih.</p>",
         f'<p style="text-align:right">Manajemen<br/>{e(doc.vendor_name)}</p>']  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 10.5pt;}", A4


def o_daftar_harga(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    rows = "".join(
        f'<tr><td style="width:8%">{i}</td><td style="width:62%">{e(it.description)}</td><td style="width:30%;text-align:right">{doc.amt(it.unit_price)}</td></tr>'
        for i, it in enumerate(doc.items, 1)
    )
    h = ['<div style="text-align:center;font-size:16pt;font-weight:bold">DAFTAR HARGA</div>',
         f'<div style="text-align:center">{e(doc.vendor_name)} &middot; berlaku mulai {doc.dt(doc.issue_date)}</div>',
         '<div style="margin-top:10px"></div>',
         f'<table style="width:100%"><tr style="font-weight:bold;background-color:#e5e7eb"><td>No</td><td>Nama Produk</td><td style="text-align:right">Harga</td></tr>{rows}</table>',
         "<p>Harga dapat berubah sewaktu-waktu tanpa pemberitahuan. Pemesanan minimal 5 unit mendapat potongan khusus.</p>",
         f"<p>Pemesanan: {e(doc.vendor_phone)}</p>"]  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 10pt;}", A4


def o_cv(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    name = doc.extra["people"][2]
    h = ['<div style="text-align:center;font-size:15pt;font-weight:bold">DAFTAR RIWAYAT HIDUP</div><br/>',
         f'<table><tr><td style="width:35%">Nama Lengkap</td><td>: {e(name)}</td></tr>'
         f'<tr><td>Tempat, Tanggal Lahir</td><td>: {e(doc.vendor_city)}, {rng.randint(1, 28)} {rng.choice(["Januari", "Mei", "Agustus", "Oktober"])} {rng.randint(1975, 2003)}</td></tr>'
         f'<tr><td>Alamat</td><td>: {e(doc.vendor_street)}, {e(doc.vendor_city)}</td></tr><tr><td>Telepon</td><td>: {e(doc.vendor_phone)}</td></tr></table>',
         "<p><b>Pendidikan</b></p><ul>"
         f'<li>S1 {rng.choice(["Akuntansi", "Teknik Informatika", "Manajemen", "Hukum"])}, Universitas {rng.choice(["Negeri", "Swasta"])} {e(doc.vendor_city)} ({rng.randint(2005, 2022)})</li>'
         f'<li>SMA Negeri {rng.randint(1, 12)} {e(doc.vendor_city)}</li></ul>',
         "<p><b>Pengalaman Kerja</b></p><ul>"
         f'<li>{rng.randint(2015, 2022)} - sekarang: Staf di {e(doc.vendor_name)}</li><li>Magang di dinas pemerintah kota</li></ul>',
         "<p><b>Keahlian</b>: Microsoft Excel, pembukuan, komunikasi, bahasa Inggris</p>"]  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 10pt;}", A4


def o_surat_jalan(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    rows = "".join(
        f'<tr><td style="width:8%">{i}</td><td style="width:62%">{e(it.description)}</td><td style="width:15%;text-align:right">{it.qty}</td>'
        f'<td style="width:15%">{rng.choice(["pcs", "dus", "unit", "sak"])}</td></tr>'
        for i, it in enumerate(doc.items, 1)
    )
    h = [_kop(doc), '<div style="text-align:center;font-size:15pt;font-weight:bold">SURAT JALAN</div>',
         f'<table style="width:100%"><tr><td style="width:55%">Kepada: {e(doc.customer or "")}<br/>Alamat: {e(doc.customer_street or doc.vendor_street)}</td>'
         f'<td style="width:45%">No. SJ: {doc.extra["number"]}<br/>Tanggal: {doc.dt(doc.issue_date)}<br/>Kendaraan: B {rng.randint(1000, 9999)} {rng.choice(["KJA", "TRU", "PQS"])}</td></tr></table>',
         '<div style="margin-top:10px"></div>',
         f'<table style="width:100%"><tr style="font-weight:bold;background-color:#e5e7eb"><td>No</td><td>Nama Barang</td><td style="text-align:right">Jumlah</td><td>Satuan</td></tr>{rows}</table>',
         '<p>Barang telah diterima dalam keadaan baik dan lengkap.</p>',
         '<table style="width:100%;margin-top:20px"><tr><td style="width:33%;text-align:center">Penerima<br/><br/><br/>(..........)</td>'
         '<td style="width:33%;text-align:center">Sopir<br/><br/><br/>(..........)</td><td style="width:33%;text-align:center">Gudang<br/><br/><br/>(..........)</td></tr></table>']  # fmt: skip
    return "".join(h), "body {font-family: sans-serif; font-size: 9.5pt;}", A4


def o_heldout_notulen(doc: SynthDoc, rng: random.Random) -> tuple[str, str, Page]:
    """Held-out 'other' layout: meeting minutes."""
    p = doc.extra["people"]
    h = [_kop(doc), '<div style="text-align:center;font-size:14pt;font-weight:bold">NOTULEN RAPAT</div>',
         f'<table><tr><td style="width:30%">Hari/Tanggal</td><td>: {fmt_date(doc.issue_date, "day_d_month_y") if doc.issue_date else ""}</td></tr>'
         f'<tr><td>Pimpinan rapat</td><td>: {e(p[0])}</td></tr><tr><td>Notulis</td><td>: {e(p[1])}</td></tr>'
         f'<tr><td>Peserta</td><td>: {", ".join(e(x) for x in p[2:6])}</td></tr></table>',
         "<p><b>Pembahasan</b></p><ol><li>Laporan progres proyek bulan berjalan.</li><li>Kendala pengadaan barang dan solusi.</li>"
         "<li>Jadwal pelatihan karyawan baru.</li></ol>",
         "<p><b>Keputusan</b></p><ol><li>Pengadaan dilanjutkan dengan pemasok alternatif.</li><li>Pelatihan dimulai bulan depan.</li></ol>",
         f'<p style="text-align:right">{e(doc.vendor_city)}, {doc.dt(doc.issue_date)}<br/>Notulis<br/><br/><br/>{e(p[1])}</p>']  # fmt: skip
    return "".join(h), "body {font-family: serif; font-size: 10pt;}", A4


RECEIPT_TEMPLATES: dict[str, Template] = {
    "r_thermal_mono": r_thermal_mono, "r_thermal_table": r_thermal_table, "r_minimarket": r_minimarket,
    "r_restaurant": r_restaurant, "r_nota_kontan": r_nota_kontan, "r_apotek": r_apotek, "r_digital": r_digital,
    "r_heldout_compact": r_heldout_compact,
}  # fmt: skip
INVOICE_TEMPLATES: dict[str, Template] = {
    "i_classic": i_classic, "i_faktur_penjualan": i_faktur_penjualan, "i_modern": i_modern, "i_service": i_service,
    "i_meta_table": i_meta_table, "i_heldout_english": i_heldout_english,
}  # fmt: skip
OTHER_TEMPLATES: dict[str, Template] = {
    "o_undangan": o_undangan, "o_surat_keterangan": o_surat_keterangan, "o_pengumuman": o_pengumuman,
    "o_daftar_harga": o_daftar_harga, "o_cv": o_cv, "o_surat_jalan": o_surat_jalan, "o_heldout_notulen": o_heldout_notulen,
}  # fmt: skip
ALL_TEMPLATES: dict[str, Template] = {**RECEIPT_TEMPLATES, **INVOICE_TEMPLATES, **OTHER_TEMPLATES}
HELD_OUT = {"r_heldout_compact", "i_heldout_english", "o_heldout_notulen"}
