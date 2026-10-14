"""Build the synthetic dataset.

    python -m ml.synthetic.generate --out data/synthetic/v1 --seed 20261011

Every document is generated from a seed derived from (dataset seed, split,
index), so the dataset is reproducible byte-for-byte. Each split gets a
``manifest.jsonl``; ``dataset.json`` records file hashes so the test splits can
be frozen and verified before every evaluation (PRD 11.2).
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path
from typing import Any

import cv2

from ml.synthetic import vocab
from ml.synthetic.augment import degrade
from ml.synthetic.model import sample_invoice, sample_other, sample_receipt
from ml.synthetic.render import html_to_pdf, pdf_to_image, reference_text
from ml.synthetic.templates import HELD_OUT, INVOICE_TEMPLATES, OTHER_TEMPLATES, RECEIPT_TEMPLATES

DEFAULT_SIZES = {"train": 1200, "val": 240, "test_seen": 200, "test_unseen": 100, "injection": 30}
TYPE_MIX = [("receipt", 0.42), ("invoice", 0.38), ("other", 0.20)]
DPI = {"receipt": 200, "invoice": 150, "other": 150}


def _seed(base: int, split: str, idx: int) -> int:
    return int.from_bytes(hashlib.sha256(f"{base}:{split}:{idx}".encode()).digest()[:8], "big")


def _pick_type(rng: random.Random, split: str) -> str:
    if split == "injection":
        return rng.choice(["receipt", "invoice"])
    r = rng.random()
    acc = 0.0
    for t, p in TYPE_MIX:
        acc += p
        if r < acc:
            return t
    return "other"


def _templates(doc_type: str, held_out: bool) -> list[str]:
    pool = {"receipt": RECEIPT_TEMPLATES, "invoice": INVOICE_TEMPLATES, "other": OTHER_TEMPLATES}[doc_type]
    return sorted(t for t in pool if (t in HELD_OUT) == held_out)


def make_document(base_seed: int, split: str, idx: int, out_dir: str) -> dict[str, Any]:
    seed = _seed(base_seed, split, idx)
    rng = random.Random(seed)
    unseen = split == "test_unseen"
    doc_type = _pick_type(rng, split)
    template = rng.choice(_templates(doc_type, held_out=unseen))
    doc_id = f"{split}_{idx:05d}"
    sampler = {"receipt": sample_receipt, "invoice": sample_invoice, "other": sample_other}[doc_type]
    doc = sampler(doc_id, template, rng, unseen)
    if split == "injection":
        doc.injection = rng.choice(vocab.INJECTION_LINES)
    fn = {**RECEIPT_TEMPLATES, **INVOICE_TEMPLATES, **OTHER_TEMPLATES}[template]
    html, css, page = fn(doc, rng)
    pdf = html_to_pdf(html, css, page)
    clean = pdf_to_image(pdf, DPI[doc_type])
    degraded, recipe = degrade(clean, seed, doc_type)

    out = Path(out_dir) / split
    out.mkdir(parents=True, exist_ok=True)
    files = {"pdf": f"{doc_id}.pdf", "clean": f"{doc_id}.png", "degraded": f"{doc_id}_deg.jpg"}
    (out / files["pdf"]).write_bytes(pdf)
    cv2.imwrite(str(out / files["clean"]), clean)
    cv2.imwrite(str(out / files["degraded"]), degraded, [cv2.IMWRITE_JPEG_QUALITY, 92])
    primary = "degraded" if rng.random() < 0.6 else "clean"
    record = {
        "doc_id": doc_id,
        "split": split,
        "doc_type": doc_type,
        "template": template,
        "unseen": unseen,
        "injection": doc.injection is not None,
        "primary": primary,
        "files": files,
        "degradation": recipe,
        "ground_truth": doc.ground_truth(),
        "reference_text": reference_text(pdf),
    }
    (out / f"{doc_id}.json").write_text(json.dumps(record, ensure_ascii=False, indent=1), encoding="utf-8")
    hashes = {k: hashlib.sha256((out / v).read_bytes()).hexdigest() for k, v in files.items()}
    hashes["json"] = hashlib.sha256((out / f"{doc_id}.json").read_bytes()).hexdigest()
    return {"doc_id": doc_id, "doc_type": doc_type, "template": template, "sha256": hashes}


def build(out_dir: str, seed: int, sizes: dict[str, int], workers: int) -> dict[str, Any]:
    summary: dict[str, Any] = {"seed": seed, "sizes": sizes, "splits": {}}
    with ProcessPoolExecutor(max_workers=workers) as pool:
        for split, n in sizes.items():
            futures = [pool.submit(make_document, seed, split, i, out_dir) for i in range(n)]
            rows = [f.result() for f in futures]
            (Path(out_dir) / split / "manifest.jsonl").write_text(
                "\n".join(json.dumps(r, ensure_ascii=False) for r in rows) + "\n", encoding="utf-8"
            )
            digest = hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()
            counts: dict[str, int] = {}
            for r in rows:
                counts[r["doc_type"]] = counts.get(r["doc_type"], 0) + 1
            summary["splits"][split] = {"n": n, "counts": counts, "digest": digest}
            print(f"{split:12s} {n:5d} docs  {counts}  digest={digest[:12]}")
    (Path(out_dir) / "dataset.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    return summary


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--out", default="data/synthetic/v1")
    ap.add_argument("--seed", type=int, default=20261011)
    ap.add_argument("--workers", type=int, default=6)
    ap.add_argument("--sizes", default="", help="e.g. train=50,val=20 (default: PRD sizes)")
    args = ap.parse_args()
    sizes = dict(DEFAULT_SIZES)
    if args.sizes:
        sizes = {k: int(v) for k, v in (kv.split("=") for kv in args.sizes.split(","))}
    build(args.out, args.seed, sizes, args.workers)


if __name__ == "__main__":
    main()
