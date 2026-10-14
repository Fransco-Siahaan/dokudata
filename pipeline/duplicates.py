"""Duplicate and anomaly detection (PRD 8.6)."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Any

import imagehash
import numpy as np
from PIL import Image

from pipeline.normalize import text_key

PHASH_MAX_DISTANCE = 6  # out of 64 bits


def perceptual_hash(image_bgr: np.ndarray) -> str:
    rgb = Image.fromarray(image_bgr[..., ::-1])
    return str(imagehash.phash(rgb, hash_size=8))


def hash_distance(a: str, b: str) -> int:
    return int(imagehash.hex_to_hash(a) - imagehash.hex_to_hash(b))


def data_key(values: dict[str, Any]) -> str | None:
    """Business key: number + vendor + total + date. ``None`` when too little is known to compare."""
    number, vendor, total = values.get("document_number"), values.get("vendor_name"), values.get("total")
    if not vendor or total is None or not (number or values.get("issue_date")):
        return None
    return "|".join([
        text_key(str(number or "")), text_key(str(vendor)), f"{float(total):.2f}", str(values.get("issue_date") or ""),
    ])  # fmt: skip


@dataclass(slots=True)
class DuplicateMatch:
    other_id: str
    reason: str  # "file_hash" | "image_hash" | "data_key"
    detail: str = ""


def find_duplicates(
    doc_id: str,
    file_sha256: str,
    phash: str | None,
    key: str | None,
    others: Iterable[tuple[str, str, str | None, str | None]],
) -> list[DuplicateMatch]:
    """Compare against ``others`` = (id, sha256, phash, data_key) of earlier documents."""
    out = []
    for oid, osha, ophash, okey in others:
        if oid == doc_id:
            continue
        if osha == file_sha256:
            out.append(DuplicateMatch(oid, "file_hash", "Berkas identik"))
        elif phash and ophash and (d := hash_distance(phash, ophash)) <= PHASH_MAX_DISTANCE:
            out.append(DuplicateMatch(oid, "image_hash", f"Gambar sangat mirip (jarak {d})"))
        elif key and okey and key == okey:
            out.append(DuplicateMatch(oid, "data_key", "Nomor, vendor, tanggal dan total sama"))
    return out


def amount_anomaly(
    value: float, history: list[float], z_threshold: float = 3.5, min_history: int = 5
) -> str | None:
    """Robust z-score (median/MAD) of a total against the same vendor's earlier totals."""
    if len(history) < min_history:
        return None
    h = np.asarray(history, dtype=float)
    med = float(np.median(h))
    mad = float(np.median(np.abs(h - med))) or 1.0
    z = 0.6745 * (value - med) / mad
    if abs(z) > z_threshold:
        return f"Total {value:,.0f} jauh dari kebiasaan vendor ini (median {med:,.0f})"
    return None
