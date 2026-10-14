"""Dataset access shared by training and evaluation."""

from __future__ import annotations

import hashlib
import json
from functools import lru_cache
from pathlib import Path
from typing import Any

DATA = Path("data/synthetic/v1")
FROZEN = Path("ml/data/frozen.json")
TEST_SPLITS = ["test_seen", "test_unseen", "injection"]


@lru_cache(maxsize=16)
def records(split: str) -> tuple[dict[str, Any], ...]:
    out = []
    for line in (DATA / split / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if line.strip():
            doc_id = json.loads(line)["doc_id"]
            out.append(json.loads((DATA / split / f"{doc_id}.json").read_text(encoding="utf-8")))
    return tuple(out)


def split_digest(split: str) -> str:
    rows = [
        json.loads(line)
        for line in (DATA / split / "manifest.jsonl").read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return hashlib.sha256(json.dumps(rows, sort_keys=True).encode()).hexdigest()


def verify_files(split: str) -> list[str]:
    """Re-hash every file of a split against its manifest. Returns the list of mismatches."""
    bad = []
    for line in (DATA / split / "manifest.jsonl").read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        for kind, digest in row["sha256"].items():
            name = f"{row['doc_id']}.json" if kind == "json" else json.loads(
                (DATA / split / f"{row['doc_id']}.json").read_text(encoding="utf-8"))["files"][kind]  # fmt: skip
            if hashlib.sha256((DATA / split / name).read_bytes()).hexdigest() != digest:
                bad.append(f"{split}/{name}")
    return bad


def freeze(note: str = "") -> dict[str, Any]:
    meta = json.loads((DATA / "dataset.json").read_text(encoding="utf-8"))
    frozen = {
        "dataset": str(DATA),
        "seed": meta["seed"],
        "note": note or "Test splits frozen before any model selection; evaluation verifies these digests.",
        "splits": {s: {"n": meta["splits"][s]["n"], "digest": split_digest(s)} for s in TEST_SPLITS},
    }
    FROZEN.parent.mkdir(parents=True, exist_ok=True)
    FROZEN.write_text(json.dumps(frozen, indent=2), encoding="utf-8")
    return frozen


def check_frozen() -> dict[str, Any]:
    """Fail loudly if the test data changed since it was frozen."""
    if not FROZEN.exists():
        raise SystemExit(
            "ml/data/frozen.json missing: run `python -m ml.freeze` once after generating the dataset"
        )
    frozen = json.loads(FROZEN.read_text(encoding="utf-8"))
    for split, info in frozen["splits"].items():
        if split_digest(split) != info["digest"]:
            raise SystemExit(
                f"test split {split} does not match its frozen digest; regenerate with the frozen seed"
            )
        bad = verify_files(split)
        if bad:
            raise SystemExit(f"{len(bad)} files in {split} changed since freezing, e.g. {bad[:3]}")
    return frozen
