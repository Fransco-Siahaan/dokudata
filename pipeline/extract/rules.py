"""Method A: OCR + rules (regex and layout heuristics), the explainable baseline (PRD 8.4).

Strategy:
  * rebuild rows from word geometry and split rows into column segments;
  * give every amount-bearing row a role (subtotal, discount, tax, total, cash,
    change) from its label, then pick the combination that satisfies
    ``subtotal - discount + tax == total`` when one exists;
  * line items are the amount rows between the header block and the first
    totals row, parsed right-to-left so numbers inside descriptions
    ("Beras 5 kg") are not mistaken for quantities;
  * the vendor is the largest non-title text segment near the top that is not
    in the customer block.
"""

from __future__ import annotations

import itertools
import re
import time
from dataclasses import dataclass

import numpy as np

from pipeline.interfaces import BBox, ExtractionInput, ExtractionResult, Line, Word, merge_bboxes
from pipeline.normalize import (
    _fix_ocr_digits,
    find_dates,
    normalize_payment_method,
    normalize_tax_id,
    normalize_vendor,
    parse_amount,
)
from pipeline.schema import Extraction, FieldValue, LineItem

ROLE_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("count", re.compile(r"^\s*(jml|jumlah)\s*item\b|^\s*total\s*qty\b")),
    ("change", re.compile(r"\bkembali(an)?\b|\bchange\b")),
    ("subtotal", re.compile(r"\bsub\s*-?\s*total\b|\btotal\s*(item|harga|biaya)\b|^\s*jumlah\s*$|\bsubtotal\b")),
    ("discount", re.compile(r"\b(diskon|disc|discount|potongan|hemat|promo)\b")),
    ("tax", re.compile(r"\b(ppn|pajak|vat|tax)\b")),
    ("total", re.compile(
        r"\b(grand\s*total|total\s*(bayar|belanja|tagihan|pembayaran)|jumlah\s*(tagihan|dibayar|rp)|amount\s*due)\b")),
    ("total_plain", re.compile(r"\btotal\b")),
    ("cash", re.compile(r"\b(tunai|cash|bayar|uang)\b")),
]  # fmt: skip

TITLE_RE = re.compile(
    r"^\W*(invoice|faktur( penjualan)?|tax invoice|tagihan jasa|nota|struk|kwitansi|bukti pembayaran|"
    r"transaksi berhasil|daftar harga|surat jalan|pengumuman)\b",
    re.IGNORECASE,
)
# "Jl." is often read as "JI." or "J1." by OCR.
ADDRESS_RE = re.compile(
    r"\b(?:j[l1i|]\.|(?:jl|jalan|telp|hp|wa|kota|kab|blok|ruko)\b|tel\.|kel\.|kec\.|rt\s*\d|rw\s*\d)|\d{4}-\d{4}",
    re.I,
)
# Gazetteer of large Indonesian cities: a bare city name under the vendor is an address line.
CITIES = {
    "jakarta", "bandung", "surabaya", "semarang", "yogyakarta", "jogja", "medan", "makassar", "denpasar", "malang",
    "bogor", "bekasi", "tangerang", "depok", "palembang", "solo", "surakarta", "pontianak", "balikpapan", "manado",
    "padang", "pekanbaru", "batam", "banjarmasin", "samarinda", "jambi", "bengkulu", "lampung", "bandar lampung",
    "serang", "cirebon", "tasikmalaya", "sukabumi", "cimahi", "karawang", "purwokerto", "tegal", "pekalongan",
    "magelang", "kudus", "madiun", "kediri", "blitar", "jember", "banyuwangi", "mataram", "kupang", "ambon",
    "jayapura", "sorong", "palu", "kendari", "gorontalo", "ternate", "aceh", "banda aceh", "pangkalpinang",
    "tanjungpinang", "palangkaraya", "tarakan", "sidoarjo", "gresik", "mojokerto", "pasuruan", "probolinggo",
}  # fmt: skip


def _is_city(text: str) -> bool:
    return text.strip(" ,.-").lower() in CITIES


CUSTOMER_RE = re.compile(
    r"\b(kepada|tagihan kepada|bill to|ditagihkan ke|klien|pembeli|pelanggan|yth)\b", re.I
)
META_RE = re.compile(
    r"\b(telp|npwp|n\.p\.w\.p|no\.|nomor|invoice|faktur|struk|transaksi|kasir|ksr|pelayan|meja|waktu|metode|kepada|"
    r"tagihan|jatuh tempo|tanggal|tgl|date|jl\.|klien|pembeli|bill|merchant|lokasi|apoteker|termin|diterbitkan)\b"
    r"|^\s*(no|item|qty|deskripsi|nama barang|banyaknya|description|uraian|#)\b",
    re.I,
)
TABLE_HEADER_RE = re.compile(
    r"\b(deskripsi|nama barang|description|uraian|banyaknya|harga|qty|jumlah|item)\b", re.I
)
DOCNO_RE = re.compile(
    r"(?:\b(?:nomor|no(?:\.|\b))\s*(?:invoice|faktur|nota|struk|transaksi|sj)?|invoice\s*(?:no\.?|#)|bill\s*#|"
    r"id\s*transaksi|\bnota\s*no\.?)\s*[:#.]?\s*(?P<num>[A-Z0-9][A-Z0-9/\-.]{2,})",
    re.I,
)
HASH_DOCNO_RE = re.compile(r"#\s?(?P<num>[A-Z0-9][A-Z0-9/\-.]{3,})", re.I)
PERCENT_RE = re.compile(r"\d+(?:[.,]\d+)?\s*%")
TIME_RE = re.compile(r"\b\d{1,2}:\d{2}(?::\d{2})?\b")
NPWP_LABEL_RE = re.compile(r"n\.?\s?p\.?\s?w\.?\s?p|tax\s*id", re.I)
NPWP_RE = re.compile(r"(?<!\d)(?:\d{16}|\d{2}[.\s]?\d{3}[.\s]?\d{3}[.\s]?\d[-.\s]?\d{3}[.\s]?\d{3})(?!\d)")
QTY_MARK_RE = re.compile(r"^(?:x(\d{1,4})|\((\d{1,4})\)|(\d{1,4})x)$", re.I)


@dataclass(slots=True)
class Segment:
    words: list[Word]
    line_index: int

    @property
    def text(self) -> str:
        return " ".join(w.text for w in self.words)

    @property
    def bbox(self) -> BBox:
        return merge_bboxes([w.bbox for w in self.words])

    @property
    def height(self) -> float:
        return float(np.median([w.bbox[3] - w.bbox[1] for w in self.words]))

    @property
    def conf(self) -> float:
        return float(np.mean([w.conf for w in self.words]))


def segments(line: Line, index: int) -> list[Segment]:
    """Split a row into column segments wherever the gap between words is unusually wide."""
    if not line.words:
        return []
    out = [[line.words[0]]]
    for prev, w in itertools.pairwise(line.words):
        # A normal word space is ~0.3x the text height; a column gap is well over 1x.
        h_prev, h_w = prev.bbox[3] - prev.bbox[1], w.bbox[3] - w.bbox[1]
        gap_limit = 1.1 * min(h_prev, h_w)
        font_change = max(h_prev, h_w) > 1.25 * max(1.0, min(h_prev, h_w))
        if w.bbox[0] - prev.bbox[2] > gap_limit or font_change:
            out.append([w])
        else:
            out[-1].append(w)
    return [Segment(ws, index) for ws in out]


@dataclass(slots=True)
class AmountRow:
    index: int
    label: str
    value: float
    words: list[Word]
    role: str | None

    @property
    def bbox(self) -> BBox:
        return merge_bboxes([w.bbox for w in self.words])

    @property
    def conf(self) -> float:
        return float(np.mean([w.conf for w in self.words])) if self.words else 0.5


def _clean_for_amounts(text: str) -> str:
    text = PERCENT_RE.sub(" ", text)
    text = TIME_RE.sub(" ", text)
    for m in find_dates(text):
        text = text.replace(m.raw, " ")
    return text


def _value_words(line: Line) -> tuple[str, float, list[Word]] | None:
    """Label text and the right-most amount of a row, with the words holding that amount."""
    words = line.words
    for j in range(len(words) - 1, -1, -1):
        raw = _clean_for_amounts(words[j].text).strip()
        value = parse_amount(raw) if re.search(r"\d", raw) else None
        if value is None:
            continue
        used = [words[j]]
        if j > 0 and words[j - 1].text.lower().rstrip(".") in ("rp", "idr"):
            used.insert(0, words[j - 1])
            j -= 1
        label = " ".join(w.text for w in words[:j])
        return label, value, used
    return None


def role_of(label: str) -> str | None:
    low = label.lower().strip(" :.")
    for role, pattern in ROLE_PATTERNS:
        if pattern.search(low):
            return "total" if role == "total_plain" else role
    return None


MONEY_RE = re.compile(r"^-?\(?(rp\.?\s?)?\d{1,3}([.,]\d{3})+([.,]\d{1,2})?(,-)?\)?$|^-?(rp\.?\s?)\d+", re.I)


def _amount_rows(lines: list[Line]) -> list[AmountRow]:
    rows: list[AmountRow] = []
    pending_label: tuple[int, str] | None = None
    for i, line in enumerate(lines):
        if NPWP_LABEL_RE.search(line.text) or (ADDRESS_RE.search(line.text) and not role_of(line.text)):
            pending_label = None
            continue
        found = _value_words(line)
        if found is None:
            # A totals label whose value slipped onto the next row (photo taken at an angle).
            pending_label = (
                (i, line.text) if role_of(line.text) in ("subtotal", "discount", "tax", "total") else None
            )
            continue
        label, value, words = found
        index = i
        if not re.search(r"[A-Za-z]{2,}", label) and pending_label and i - pending_label[0] == 1:
            # Anchor the row at the label so the item zone ends above it.
            index, label = pending_label
        pending_label = None
        role = role_of(label) if re.search(r"[A-Za-z]{2,}", label) else None
        rows.append(AmountRow(index, label, value, words, role))
    return rows


def _looks_like_money(row: AmountRow) -> bool:
    return bool(MONEY_RE.match(" ".join(w.text for w in row.words)))


def _solve_totals(
    rows: list[AmountRow], items_sum: float | None = None
) -> dict[str, tuple[AmountRow, float]]:
    """Choose subtotal/discount/tax/total rows, preferring an arithmetically consistent set."""
    by_role: dict[str, list[AmountRow]] = {}
    for r in rows:
        if r.role:
            by_role.setdefault(r.role, []).append(r)
    chosen: dict[str, tuple[AmountRow, float]] = {}
    totals = by_role.get("total", [])
    subs = by_role.get("subtotal", [])
    discs: list[AmountRow | None] = list(by_role.get("discount", [])) or [None]
    taxes: list[AmountRow | None] = list(by_role.get("tax", [])) or [None]
    for t, s, d, x in itertools.product(totals or [None], subs or [None], discs, taxes):  # type: ignore[list-item]
        if t is None or s is None:
            continue
        dv = abs(d.value) if d else 0.0
        xv = x.value if x else 0.0
        if abs(s.value - dv + xv - t.value) <= 1.0:
            chosen["total"] = (t, 0.97)
            chosen["subtotal"] = (s, 0.95)
            if d:
                chosen["discount"] = (d, 0.95)
            if x:
                chosen["tax"] = (x, 0.95)
            return chosen
    if totals:
        # Specific labels ("grand total", "total bayar") win over a bare "total"; then the largest.
        specific = [t for t in totals if not re.fullmatch(r"\W*total\W*", t.label.lower().strip())]
        pool = specific or totals
        best = max(pool, key=lambda r: r.value)
        chosen["total"] = (best, 0.75 if specific else 0.7)
    if subs:
        chosen["subtotal"] = (subs[0], 0.65)
    if by_role.get("discount"):
        chosen["discount"] = (by_role["discount"][0], 0.65)
    if by_role.get("tax"):
        chosen["tax"] = (by_role["tax"][0], 0.65)
    if "total" not in chosen:
        # No total label survived OCR: prefer an unlabelled money amount equal to the item sum
        # (adjusted by any discount/tax found), else the largest money-formatted amount.
        candidates = [r for r in rows if r.role not in ("cash", "change", "count") and _looks_like_money(r)]
        if items_sum:
            dv = abs(chosen["discount"][0].value) if "discount" in chosen else 0.0
            xv = chosen["tax"][0].value if "tax" in chosen else 0.0
            for r in reversed(candidates):
                if abs(r.value - (items_sum - dv + xv)) <= 1.0:
                    chosen["total"] = (r, 0.6)
                    return chosen
        if candidates:
            best = max(candidates, key=lambda r: r.value)
            chosen["total"] = (best, 0.3)
    return chosen


def _num_token(text: str) -> float | None:
    t = text.strip()
    if not re.search(r"\d", t) or re.search(r"[A-Za-z]{2,}", t):
        return None
    t = _fix_ocr_digits(t)
    if re.fullmatch(r"[A-Za-z]+\d+[A-Za-z]*|\d+[A-Za-z]+", t):  # "A5", "12A", "10mm", "USB-C"
        return None
    return parse_amount(t)


def _parse_item_line(
    line: Line, row_no: int | None = None
) -> tuple[list[Word], int | None, float | None, float | None, list[Word]] | None:
    """Split an item row into description words and (qty, unit_price, amount).

    ``row_no`` is the 1-based number the next item would have; a leading integer equal
    to it is treated as an invoice row number rather than a quantity.
    """
    words = [w for w in line.words if w.text.lower().rstrip(".") not in ("rp", "idr", "@", "x", "×")]
    nums: list[tuple[float, Word]] = []
    qty_marker: int | None = None
    desc_end = len(words)
    for j in range(len(words) - 1, -1, -1):
        mark = QTY_MARK_RE.match(words[j].text)
        if mark:
            qty_marker = int(next(g for g in mark.groups() if g))
            desc_end = j
            continue
        v = _num_token(words[j].text)
        if v is None:
            break
        nums.insert(0, (v, words[j]))
        desc_end = j
    if not nums:
        return None
    desc = words[:desc_end]
    value_words = [w for _, w in nums]
    vals = [v for v, _ in nums]
    lead_qty: int | None = None
    if desc and re.fullmatch(r"\d{1,4}", desc[0].text):
        lead_qty = int(desc[0].text)
        desc = desc[1:]

    def ok(q: float, p: float, a: float) -> bool:
        return q > 0 and abs(q * p - a) <= max(1.0, 0.001 * a)

    amount = vals[-1]
    qty: float | None = None
    price: float | None = None
    used = 1  # how many trailing numbers are qty/price/amount; the rest belong to the description
    lead_used = False
    q_cand = qty_marker or lead_qty
    lead_is_row = lead_qty is not None and lead_qty == row_no and qty_marker is None
    free = q_cand is None or lead_is_row  # no quantity fixed yet
    if len(vals) >= 3 and ok(vals[-3], vals[-2], vals[-1]):
        qty, price, used = vals[-3], vals[-2], 3
        lead_used = lead_qty is not None  # a leading integer before qty/price/amount is a row number
    elif len(vals) >= 2:
        a, b = vals[-2], vals[-1]
        if q_cand and ok(q_cand, a, b):
            qty, price, used = q_cand, a, 2
            lead_used = qty_marker is None
        # When a leading integer does not fit as quantity it is a row number ("3  Langganan ... 475.000 950.000").
        elif free and a.is_integer() and 0 < a <= 1000 and (b / a).is_integer() and b >= a:
            qty, price, used = a, b / a, 2
            lead_used = lead_is_row
        elif free and a > 1000 and b > 1000 and ok(round(b / a), a, b):
            qty, price, used = round(b / a), a, 2
            lead_used = lead_is_row
    if used == 1 and q_cand:
        qty, price = q_cand, amount / q_cand
        lead_used = qty_marker is None
    if lead_qty is not None and not lead_used:
        desc = [next(w for w in words if re.fullmatch(r"\d{1,4}", w.text)), *desc]
    desc = desc + [w for _, w in nums[:-used]]
    value_words = [w for _, w in nums[-used:]]
    return desc, int(qty) if qty else None, price, amount, value_words


ParsedItem = tuple[list[Word], int | None, float | None, float | None, list[Word]]


def _is_weak(parsed: ParsedItem) -> bool:
    """One small bare number next to text ("ISI 25") is part of a description, not a price."""
    desc, qty, _, amount, value_words = parsed
    return (
        bool(desc)
        and len(value_words) == 1
        and qty is None
        and amount is not None
        and amount < 1000
        and re.fullmatch(r"\d{1,3}", value_words[0].text.strip()) is not None
    )


def _items(lines: list[Line], start: int, end: int) -> list[LineItem]:
    items: list[LineItem] = []
    pending: list[Word] = []
    last_complete: LineItem | None = None
    for i in range(start, end):
        line = lines[i]
        text = line.text.strip()
        if not text or re.fullmatch(r"[-=_.*~\s]+", text):
            pending, last_complete = [], None
            continue
        parsed = _parse_item_line(line, len(items) + 1)
        if parsed is not None and _is_weak(parsed):
            parsed = None  # "ISI 25", "60 ml": a wrapped description, not a priced row
        if parsed is None:
            if not re.search(r"[A-Za-z]", text) or (
                last_complete is None and not re.search(r"[A-Za-z]{2,}", text)
            ):
                continue
            nxt = lines[i + 1] if i + 1 < end else None
            nxt_parsed = _parse_item_line(nxt, len(items) + 1) if nxt is not None else None
            next_is_values_only = nxt_parsed is not None and not nxt_parsed[0] and not _is_weak(nxt_parsed)
            if last_complete is not None and not next_is_values_only and not pending:
                last_complete.description = f"{last_complete.description} {text}".strip()
                prev = last_complete.bbox
                prev_box = (prev[0], prev[1], prev[2], prev[3]) if prev else line.bbox
                last_complete.bbox = list(merge_bboxes([prev_box, line.bbox]))
            else:
                pending.extend(line.words)
            continue
        desc_words, qty, price, amount, value_words = parsed
        if not desc_words and pending:
            desc_words = pending
        pending = []
        description = " ".join(w.text for w in desc_words).strip(" :-")
        if not description or not re.search(r"[A-Za-z]", description) or amount is None or amount <= 0:
            last_complete = None
            continue
        all_words = desc_words + value_words
        item = LineItem(
            description=description,
            qty=float(qty) if qty else None,
            unit_price=price,
            amount=amount,
            confidence=round(0.75 * float(np.mean([w.conf for w in all_words])), 3),
            bbox=list(merge_bboxes([w.bbox for w in all_words])),
            page=line.page,
        )
        items.append(item)
        last_complete = item
    return items


def _items_start(lines: list[Line], end: int) -> int:
    start = 0
    for i in range(end):
        text = lines[i].text
        is_header = len(TABLE_HEADER_RE.findall(text)) >= 2 and _value_words(lines[i]) is None
        if is_header or META_RE.search(text) or find_dates(text) or ADDRESS_RE.search(text):
            start = i + 1
    return start


def _vendor(lines: list[Line]) -> tuple[str, Segment, float] | None:
    n = len(lines)
    if n == 0:
        return None
    for i, line in enumerate(lines[: max(3, n // 2)]):
        m = re.match(r"^\s*merchant\s*:?\s*(.+)$", line.text, re.I)
        if m:
            segs = segments(line, i)
            seg = segs[-1] if len(segs) > 1 else segs[0]
            name = m.group(1) if len(segs) == 1 else seg.text
            if i + 1 < n and not re.match(r"^\s*(lokasi|npwp|id|waktu)", lines[i + 1].text, re.I):
                nxt = lines[i + 1].text.strip()
                if nxt and not _value_words(lines[i + 1]):
                    name = f"{name} {nxt}"
            return name, seg, 0.85
    page_h = max((line.bbox[3] for line in lines), default=1.0)
    limit = page_h * 0.35
    customer_lines: set[int] = set()
    for i, line in enumerate(lines):
        if CUSTOMER_RE.search(line.text):
            customer_lines.update({i, i + 1, i + 2})
    cands: list[tuple[float, Segment]] = []
    for i, line in enumerate(lines):
        if line.bbox[1] > limit or i in customer_lines:
            continue
        for seg in segments(line, i):
            text = seg.text.strip(" *~:-")
            letters = sum(c.isalpha() for c in text)
            if letters < 3 or letters / max(1, len(text)) < 0.6:
                continue
            if TITLE_RE.search(text) or ADDRESS_RE.search(text) or META_RE.search(text) or find_dates(text):
                continue
            if TABLE_HEADER_RE.fullmatch(text.strip()) or CUSTOMER_RE.search(text) or _is_city(text):
                continue
            score = seg.height * (
                1.0 + 0.3 * bool(re.match(r"(pt|cv|ud|toko|warung|apotek|rumah makan|kedai)\b", text, re.I))
            )
            score -= 0.002 * seg.bbox[1]  # mild preference for higher on the page
            cands.append((score, seg))
    if not cands:
        return None
    score, best = max(cands, key=lambda c: c[0])
    name = best.text.strip(" *~:-")
    # Join a wrapped second line of the same size directly below (e.g. "... Sentosa" / "Indonesia").
    joined = False
    for nxt_i in range(best.line_index + 1, min(n, best.line_index + 3)):
        for seg in segments(lines[nxt_i], nxt_i):
            overlap = min(seg.bbox[2], best.bbox[2]) - max(seg.bbox[0], best.bbox[0])
            text = seg.text.strip()
            if (
                overlap > 0
                and -0.5 * best.height <= seg.bbox[1] - best.bbox[3] < 0.6 * best.height
                and abs(seg.height - best.height) <= 0.2 * best.height
                and not ADDRESS_RE.search(text)
                and not _is_city(text)
                and not META_RE.search(text)
                and not find_dates(text)
                and sum(c.isalpha() for c in text) >= 3
            ):
                name = f"{name} {text}"
                joined = True
                break
        if joined:
            break
    second = sorted((c[0] for c in cands), reverse=True)[1] if len(cands) > 1 else 0.0
    margin = (score - second) / max(score, 1e-6)
    return name, best, round(min(0.9, 0.5 + margin), 3)


def _document_number(lines: list[Line]) -> tuple[str, Line, float] | None:
    for line in lines:
        text = line.text
        if ADDRESS_RE.search(text) and not re.search(
            r"invoice|faktur|nota|struk|transaksi|nomor", text, re.I
        ):
            continue
        m = DOCNO_RE.search(text)
        if m:
            return m.group("num").rstrip(".-/"), line, 0.8
    for line in lines:
        m = HASH_DOCNO_RE.search(line.text)
        if m:
            return m.group("num").rstrip(".-/"), line, 0.6
    for line in lines[:12]:
        m = re.search(r"\d{1,2}:\d{2}\s*/\s*(?P<num>[A-Z0-9][A-Z0-9/\-]{3,})", line.text)
        if m:
            return m.group("num"), line, 0.6
    return None


def _dates(lines: list[Line]) -> tuple[tuple[str, Line, float] | None, tuple[str, Line, float] | None]:
    issue = due = None
    first: tuple[str, Line, float] | None = None
    for i, line in enumerate(lines):
        # OCR sometimes glues the time onto the year: "29/12/202509:58".
        text = re.sub(r"(\d{1,2}[/\-.]\d{1,2}[/\-.]\d{4})(?=\d{1,2}[:.]\d{2})", r"\1 ", line.text)
        # A narrow receipt can wrap "26 Agustus" / "2026" onto two rows.
        if i + 1 < len(lines) and re.search(r"\d{1,2}\s+[A-Za-z]{3,9}\.?$", text):
            nxt = re.match(r"^\s*(\d{4})\b", lines[i + 1].text)
            if nxt:
                text = f"{text} {nxt.group(1)}"
        found = find_dates(text)
        if not found:
            continue
        if re.search(r"jatuh\s*tempo|due\s*date|termin", text, re.I):
            due = due or (found[-1].iso, line, 0.85)
            continue
        if issue is None and re.search(r"\b(tanggal|tgl|date|diterbitkan|waktu|invoice date)\b", text, re.I):
            issue = (found[0].iso, line, 0.85)
        if first is None:
            first = (found[0].iso, line, 0.6)
    return issue or first, due


def _tax_id(lines: list[Line]) -> tuple[str, Line, float] | None:
    for line in lines:
        if NPWP_LABEL_RE.search(line.text):
            m = NPWP_RE.search(line.text)
            if m:
                digits = normalize_tax_id(m.group(0))
                if digits:
                    return digits, line, 0.85
    return None


def _payment(lines: list[Line], from_index: int) -> tuple[str, Line, float] | None:
    has_change = any(
        re.search(r"\bkembali(an)?\b|\bchange\b", line.text, re.I) for line in lines[from_index:]
    )
    for line in lines[from_index:]:
        method = normalize_payment_method(line.text)
        if method:
            return method, line, 0.8
    for line in lines:
        if re.match(r"^\s*metode\b", line.text, re.I):
            method = normalize_payment_method(line.text)
            if method:
                return method, line, 0.8
    if has_change:
        for line in lines[from_index:]:
            if re.search(r"\b(bayar|uang)\b", line.text, re.I):
                return "cash", line, 0.6
    return None


def _fv(
    value: object, conf: float, words_or_bbox: BBox | None, page: int, raw: str | None = None
) -> FieldValue:
    return FieldValue(
        value=value,
        confidence=round(conf, 3),
        source="rules",
        bbox=list(words_or_bbox) if words_or_bbox else None,
        page=page,
        raw=raw,
    )


class RulesExtractor:
    name = "rules"
    requires_ocr = True

    def extract(self, inp: ExtractionInput) -> ExtractionResult:
        start = time.perf_counter()
        if inp.ocr is None:
            raise ValueError("rules extractor requires OCR output")
        lines = inp.ocr.lines()
        ex = Extraction()
        rows = _amount_rows(lines)
        totals_idx = [r.index for r in rows if r.role in ("subtotal", "discount", "tax", "total", "count")]
        end = min(totals_idx) if totals_idx else len(lines)
        ex.line_items = _items(lines, _items_start(lines, end), end)
        items_sum = sum(li.amount for li in ex.line_items if li.amount) or None
        chosen = _solve_totals(rows, items_sum)
        role_map = {"total": "total", "subtotal": "subtotal", "discount": "discount", "tax": "tax_amount"}
        for role, field in role_map.items():
            if role in chosen:
                row, conf = chosen[role]
                value = abs(row.value) if role == "discount" else row.value
                page = lines[row.index].page
                setattr(
                    ex,
                    field,
                    _fv(value, conf * row.conf, row.bbox, page, " ".join(w.text for w in row.words)),
                )

        vendor = _vendor(lines)
        if vendor:
            name, seg, conf = vendor
            ex.vendor_name = _fv(
                normalize_vendor(name), conf * seg.conf, seg.bbox, lines[seg.line_index].page, name
            )
        docno = _document_number(lines)
        if docno:
            number, line, conf = docno
            ex.document_number = _fv(number, conf * line.conf, line.bbox, line.page, number)
        issue, due = _dates(lines)
        if issue:
            ex.issue_date = _fv(issue[0], issue[2] * issue[1].conf, issue[1].bbox, issue[1].page)
        if due:
            ex.due_date = _fv(due[0], due[2] * due[1].conf, due[1].bbox, due[1].page)
        tax_id = _tax_id(lines)
        if tax_id:
            ex.vendor_tax_id = _fv(tax_id[0], tax_id[2] * tax_id[1].conf, tax_id[1].bbox, tax_id[1].page)
        pay = _payment(lines, end)
        if pay:
            ex.payment_method = _fv(pay[0], pay[2] * pay[1].conf, pay[1].bbox, pay[1].page)
        return ExtractionResult(ex, self.name, latency_ms=(time.perf_counter() - start) * 1000)
