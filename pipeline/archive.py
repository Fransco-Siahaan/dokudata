"""Archive naming and folder layout (PRD 7.5, appendix 22.2)."""

from __future__ import annotations

import re
import unicodedata
from typing import Any

DEFAULT_NAME_PATTERN = "{tanggal}_{vendor}_{nomor}_{total}"
DEFAULT_FOLDER_PATTERN = "Arsip/{tahun}/{bulan}/{jenis}"
TYPE_FOLDER = {"receipt": "Nota", "invoice": "Faktur", "other": "Lainnya"}
_ALLOWED = {"tanggal", "vendor", "nomor", "total", "tahun", "bulan", "jenis"}


def _slug(text: str, camel: bool = True, max_len: int = 40) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    words = re.findall(r"[A-Za-z0-9]+", text)
    if camel:
        out = "".join(w[:1].upper() + w[1:].lower() if not w.isupper() or len(w) > 3 else w for w in words)
    else:
        out = "-".join(words)
    return out[:max_len] or "Tanpa"


def _safe_number(text: str) -> str:
    return re.sub(r"[^A-Za-z0-9\-]+", "-", text).strip("-")[:40] or "TanpaNomor"


def placeholders(values: dict[str, Any], doc_type: str) -> dict[str, str]:
    date = str(values.get("issue_date") or "")
    year, month = (date[:4], date[5:7]) if re.fullmatch(r"\d{4}-\d{2}-\d{2}", date) else ("TanpaTahun", "00")
    total = values.get("total")
    return {
        "tanggal": date or "TanpaTanggal",
        "vendor": _slug(str(values.get("vendor_name") or "TanpaVendor")),
        "nomor": _safe_number(str(values.get("document_number") or "")),
        "total": str(int(round(float(total)))) if total is not None else "0",
        "tahun": year,
        "bulan": month,
        "jenis": TYPE_FOLDER.get(doc_type, "Lainnya"),
    }


def validate_pattern(pattern: str) -> None:
    names = set(re.findall(r"{(\w+)}", pattern))
    unknown = names - _ALLOWED
    if unknown:
        raise ValueError(f"placeholder tidak dikenal: {', '.join(sorted(unknown))}")
    if ".." in pattern or pattern.startswith(("/", "\\")):
        raise ValueError("pola tidak boleh keluar dari folder arsip")


def archive_path(
    values: dict[str, Any],
    doc_type: str,
    ext: str,
    name_pattern: str = DEFAULT_NAME_PATTERN,
    folder_pattern: str = DEFAULT_FOLDER_PATTERN,
) -> str:
    """``Arsip/2026/03/Nota/2026-03-14_TokoMajuJaya_NT-20260314-0231_1250000.pdf``"""
    validate_pattern(name_pattern)
    validate_pattern(folder_pattern)
    ph = placeholders(values, doc_type)
    name = name_pattern.format(**ph)
    folder = folder_pattern.format(**ph)
    name = re.sub(r"[^\w\-.]+", "_", name)
    folder = "/".join(re.sub(r"[^\w\-]+", "_", part) for part in folder.split("/") if part)
    return f"{folder}/{name}.{ext.lstrip('.')}"


def dedupe_paths(paths: list[str]) -> list[str]:
    """Append _2, _3 ... to repeated archive paths so nothing is overwritten in the ZIP."""
    seen: dict[str, int] = {}
    out = []
    for p in paths:
        n = seen.get(p, 0) + 1
        seen[p] = n
        if n == 1:
            out.append(p)
        else:
            stem, dot, ext = p.rpartition(".")
            out.append(f"{stem}_{n}{dot}{ext}")
    return out
