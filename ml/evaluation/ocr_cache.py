"""Run OCR once per (engine, preprocessing, split, document, variant) and cache the words as JSON.

    python -m ml.evaluation.ocr_cache --engine rapidocr --splits train,val --variants primary
    python -m ml.evaluation.ocr_cache --engine rapidocr --splits test_seen,test_unseen --variants clean,degraded --no-preprocess

Training, threshold selection and evaluation all read from this cache, so the
expensive step runs once and every experiment sees identical OCR output.
"""

from __future__ import annotations

import argparse
import json
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path
from typing import Any

from pipeline.interfaces import OCRDocument, OCRPage, Word

DATA = Path("data/synthetic/v1")
CACHE = Path("data/cache/ocr")


def cache_path(engine: str, preprocess: bool, split: str, doc_id: str, variant: str) -> Path:
    return CACHE / engine / ("pp" if preprocess else "raw") / split / f"{doc_id}_{variant}.json"


def to_json(ocr: OCRDocument, info: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "pages": [
            {"engine": p.engine, "width": p.width, "height": p.height, "elapsed_ms": round(p.elapsed_ms, 1),
             "words": [[w.text, [round(c, 1) for c in w.bbox], round(w.conf, 4)] for w in p.words]}
            for p in ocr.pages
        ],
        "preprocess": info,
    }  # fmt: skip


def from_json(data: dict[str, Any]) -> OCRDocument:
    pages = []
    for i, p in enumerate(data["pages"]):
        words = [Word(t, (b[0], b[1], b[2], b[3]), c, i) for t, b, c in p["words"]]
        pages.append(OCRPage(words, p["width"], p["height"], p["engine"], i, p.get("elapsed_ms", 0.0)))
    return OCRDocument(pages)


def load_cached(engine: str, preprocess: bool, split: str, doc_id: str, variant: str) -> OCRDocument | None:
    p = cache_path(engine, preprocess, split, doc_id, variant)
    return from_json(json.loads(p.read_text(encoding="utf-8"))) if p.exists() else None


_engine: Any = None


def _work(
    engine_name: str, preprocess: bool, split: str, rec: dict[str, Any], variant: str
) -> tuple[str, float]:
    import cv2

    from pipeline.ocr import get_ocr_engine, run_ocr
    from pipeline.preprocess import PreprocessOptions
    from pipeline.preprocess import preprocess as run_pp

    global _engine
    if _engine is None:
        _engine = get_ocr_engine(engine_name)
    out = cache_path(engine_name, preprocess, split, rec["doc_id"], variant)
    if out.exists():
        return rec["doc_id"], 0.0
    img = cv2.imread(str(DATA / split / rec["files"][variant]))
    t0 = time.perf_counter()
    opts = PreprocessOptions() if preprocess else PreprocessOptions(False, False, False, False)
    img, info = run_pp(img, opts)
    t_pp = (time.perf_counter() - t0) * 1000
    ocr = run_ocr(_engine, [img])
    out.parent.mkdir(parents=True, exist_ok=True)
    payload = to_json(ocr, [{"steps": info.steps, "skew": info.skew_angle, "preprocess_ms": round(t_pp, 1)}])
    out.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return rec["doc_id"], ocr.elapsed_ms


def records(split: str) -> list[dict[str, Any]]:
    out = []
    for line in (DATA / split / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            doc_id = json.loads(line)["doc_id"]
            out.append(json.loads((DATA / split / f"{doc_id}.json").read_text(encoding="utf-8")))
    return out


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engine", default="rapidocr")
    ap.add_argument("--splits", default="train,val,test_seen,test_unseen,injection")
    ap.add_argument("--variants", default="primary", help="primary | clean | degraded, comma separated")
    ap.add_argument("--no-preprocess", action="store_true")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    jobs = []
    for split in args.splits.split(","):
        recs = records(split)[: args.limit or None]
        for rec in recs:
            for v in args.variants.split(","):
                jobs.append((split, rec, rec["primary"] if v == "primary" else v))
    print(f"{len(jobs)} OCR jobs ({args.engine}, preprocess={not args.no_preprocess})", flush=True)
    t0 = time.time()
    with ProcessPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(_work, args.engine, not args.no_preprocess, s, r, v) for s, r, v in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            f.result()
            if i % 100 == 0:
                print(f"  {i}/{len(jobs)}  {time.time() - t0:.0f}s", flush=True)
    print(f"done in {time.time() - t0:.0f}s", flush=True)


if __name__ == "__main__":
    main()
