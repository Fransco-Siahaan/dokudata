"""Build the public demo samples (apps/api/samples) from a dedicated 'demo' split.

    python -m ml.synthetic.make_samples

Samples never come from the test splits, so trying the demo does not leak test data.
"""

from __future__ import annotations

import json
import random
import shutil
from pathlib import Path

import cv2

from ml.synthetic import vocab
from ml.synthetic.augment import degrade
from ml.synthetic.generate import DPI, _seed
from ml.synthetic.model import sample_invoice, sample_other, sample_receipt
from ml.synthetic.render import html_to_pdf, pdf_to_image
from ml.synthetic.templates import ALL_TEMPLATES

OUT = Path("apps/api/samples")
SEED = 777

SPECS = [
    # name, template, doc_type, variant, injection, title, description
    (
        "struk-minimarket-foto",
        "r_minimarket",
        "receipt",
        "photo",
        False,
        "Struk minimarket",
        "foto miring di atas meja",
    ),
    ("nota-restoran", "r_restaurant", "receipt", "clean", False, "Nota restoran", "struk termal, PPN 11%"),
    ("faktur-pdf", "i_classic", "invoice", "pdf", False, "Faktur PDF digital", "PDF dengan lapisan teks"),
    (
        "faktur-scan",
        "i_faktur_penjualan",
        "invoice",
        "scan",
        False,
        "Faktur penjualan",
        "hasil scan, ada terbilang",
    ),
    (
        "nota-kontan",
        "r_nota_kontan",
        "receipt",
        "scan",
        False,
        "Nota kontan",
        "ada nama pelanggan sebagai pengecoh",
    ),
    (
        "bukti-qris",
        "r_digital",
        "receipt",
        "clean",
        False,
        "Bukti pembayaran QRIS",
        "vendor ditulis sebagai Merchant",
    ),
    (
        "nota-injeksi",
        "r_thermal_mono",
        "receipt",
        "clean",
        True,
        "Nota berisi prompt injection",
        "uji keselamatan AI",
    ),
    (
        "surat-undangan",
        "o_undangan",
        "other",
        "clean",
        False,
        "Surat undangan",
        "bukan nota/faktur: harus ditolak",
    ),
]


def main() -> None:
    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)
    index = []
    for i, (name, template, doc_type, variant, inject, title, desc) in enumerate(SPECS):
        seed = _seed(SEED, "demo", i)
        rng = random.Random(seed)
        sampler = {"receipt": sample_receipt, "invoice": sample_invoice, "other": sample_other}[doc_type]
        doc = sampler(name, template, rng, False)
        if inject:
            doc.injection = vocab.INJECTION_LINES[0]
        html, css, page = ALL_TEMPLATES[template](doc, rng)
        pdf = html_to_pdf(html, css, page)
        img = pdf_to_image(pdf, DPI[doc_type])
        if variant == "pdf":
            file = f"{name}.pdf"
            (OUT / file).write_bytes(pdf)
        else:
            if variant in ("photo", "scan"):
                for attempt in range(40):
                    out, recipe = degrade(img, seed + attempt, doc_type)
                    if recipe["mode"] == variant:
                        img = out
                        break
            file = f"{name}.jpg"
            cv2.imwrite(str(OUT / file), img, [cv2.IMWRITE_JPEG_QUALITY, 90])
        h, w = img.shape[:2]
        thumb = cv2.resize(img, (360, int(h * 360 / w)), interpolation=cv2.INTER_AREA)
        cv2.imwrite(
            str(OUT / f"{name}.thumb.jpg"), thumb[: min(thumb.shape[0], 480)], [cv2.IMWRITE_JPEG_QUALITY, 82]
        )
        index.append({"name": name, "file": file, "thumbnail": f"{name}.thumb.jpg", "title": title, "doc_type": doc_type,
                      "description": desc, "ground_truth": doc.ground_truth()})  # fmt: skip
        print(f"{name:24s} {file}")
    (OUT / "samples.json").write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
