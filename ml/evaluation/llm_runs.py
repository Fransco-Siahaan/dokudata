"""Run the LLM extractors (methods B and C) on evaluation documents and cache their answers.

    python -m ml.evaluation.llm_runs --engines llm_ocr,llm_vision --splits test_seen,test_unseen,injection
    python -m ml.evaluation.llm_runs ... --yes        # actually call the API

Every call costs money, so without ``--yes`` the script only prints the plan and
an estimate. Answers are cached under data/cache/llm/, so evaluation re-runs are free.
"""

from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

import cv2

from ml.common import DATA, records
from ml.evaluation.harness import llm_cache_path, ocr_for, variant_of
from pipeline.extract.llm import (
    LLM_SCHEMA,
    PROMPT_OCR,
    PROMPT_VISION,
    SYSTEM_PROMPT,
    _image_block,
    _ocr_lines_text,
)
from pipeline.llm import DEFAULT_MODEL, PRICES_PER_MTOK, ClaudeClient, LLMError


def estimate_tokens(engine: str, rec: dict[str, Any], variant: str) -> tuple[int, int]:
    system = len(SYSTEM_PROMPT) // 4 + 900  # schema overhead
    if engine == "llm_ocr":
        ocr = ocr_for(rec, variant)
        return system + len(_ocr_lines_text(ocr) if ocr else "") // 3, 700
    img = cv2.imread(str(DATA / rec["split"] / rec["files"][variant_of(rec, variant)]))
    h, w = img.shape[:2]
    s = min(1.0, 1568 / max(h, w))
    return system + int(w * s * h * s / 750), 700


def run_one(client: ClaudeClient, engine: str, rec: dict[str, Any], variant: str) -> str:
    path = llm_cache_path(engine, rec, variant)
    if path.exists():
        return "cached"
    if engine == "llm_ocr":
        ocr = ocr_for(rec, variant)
        if ocr is None:
            return "no-ocr"
        content = [{"type": "text", "text": PROMPT_OCR.format(lines=_ocr_lines_text(ocr))}]
    else:
        img = cv2.imread(str(DATA / rec["split"] / rec["files"][variant_of(rec, variant)]))
        content = [_image_block(img), {"type": "text", "text": PROMPT_VISION}]
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        resp = client.generate_json(system=SYSTEM_PROMPT, content=content, schema=LLM_SCHEMA)
        payload = {"output": resp.data, "meta": {"model": resp.model, "input_tokens": resp.input_tokens,
                   "output_tokens": resp.output_tokens, "latency_ms": round(resp.latency_ms, 1),
                   "cost_usd": round(resp.cost_usd, 6)}}  # fmt: skip
    except LLMError as exc:
        payload = {"error": str(exc)}
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return "error" if "error" in payload else "ok"


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--engines", default="llm_ocr,llm_vision")
    ap.add_argument("--splits", default="test_seen,test_unseen,injection")
    ap.add_argument("--variants", default="clean,degraded")
    ap.add_argument("--limit", type=int, default=0, help="documents per split (0 = all)")
    ap.add_argument("--workers", type=int, default=4)
    ap.add_argument("--yes", action="store_true", help="confirm spending money on API calls")
    args = ap.parse_args()

    jobs = []
    for split in args.splits.split(","):
        recs = [r for r in records(split) if r["doc_type"] != "other"][: args.limit or None]
        for rec in recs:
            for variant in args.variants.split(","):
                for engine in args.engines.split(","):
                    if not llm_cache_path(engine, rec, variant).exists():
                        jobs.append((engine, rec, variant))
    model = DEFAULT_MODEL
    pin, pout = PRICES_PER_MTOK[model]
    tin = tout = 0
    for engine, rec, variant in jobs:
        a, b = estimate_tokens(engine, rec, variant)
        tin, tout = tin + a, tout + b
    cost = (tin * pin + tout * pout) / 1e6
    print(f"{len(jobs)} uncached calls; ~{tin / 1e6:.2f}M input + {tout / 1e6:.2f}M output tokens; "
          f"estimated ${cost:.2f} on {model} (check current pricing)")  # fmt: skip
    if not args.yes:
        print("dry run: add --yes to call the API")
        return
    client = ClaudeClient()
    counts: dict[str, int] = {}
    with ThreadPoolExecutor(max_workers=args.workers) as pool:
        futs = [pool.submit(run_one, client, e, r, v) for e, r, v in jobs]
        for i, f in enumerate(as_completed(futs), 1):
            st = f.result()
            counts[st] = counts.get(st, 0) + 1
            if i % 25 == 0:
                print(f"  {i}/{len(jobs)} {counts}", flush=True)
    print(f"done: {counts}")


if __name__ == "__main__":
    main()
