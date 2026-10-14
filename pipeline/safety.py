"""Prompt-injection detection on document text (PRD 16.3).

The extractor never lets document text act on the system (no tools, strict
schema, code-side decisions). This detector adds a review flag so a human sees
documents that *try* to instruct a model, whatever the model did with them.
"""

from __future__ import annotations

import re

INJECTION_PATTERNS = [
    r"\b(abaikan|ignore|disregard)\b.{0,40}\b(instruksi|instructions?|perintah|prompt|aturan|rules)\b",
    r"\b(system|sistem)\s*(prompt)?\s*:",
    r"\b(note|catatan|instruksi)\s+(to|untuk)\s+(the\s+)?(ai|model|sistem|system|llm|asisten|assistant)\b",
    r"\b(setujui|approve|mark\b.{0,30}\bapproved)\b",
    r"\b(you are|anda adalah)\s+(now\s+)?(a|an|sekarang)\b",
    r"\breport that value instead\b",
]
_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def find_injection(text: str) -> list[str]:
    """Return the suspicious snippets found in ``text`` (empty when clean)."""
    hits = []
    for pattern in _RE:
        for m in pattern.finditer(text):
            start = max(0, m.start() - 20)
            hits.append(text[start : m.end() + 20].replace("\n", " ").strip())
    return hits
