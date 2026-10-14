"""Auto-approve vs. human review (PRD 6.3)."""

from __future__ import annotations

from dataclasses import dataclass

from pipeline.schema import REQUIRED_FIELDS, Extraction, ValidationFinding


@dataclass(slots=True)
class Decision:
    decision: str  # auto_approved | needs_review | rejected
    reasons: list[str]
    document_confidence: float


def decide(
    doc_type: str,
    classifier_conf: float,
    ex: Extraction,
    findings: list[ValidationFinding],
    field_conf: dict[str, float],
    field_threshold: float,
    classifier_threshold: float,
    flags: list[str] | None = None,
) -> Decision:
    """A document is auto-approved only if every gate passes; otherwise each failing gate is a reason."""
    reasons: list[str] = []
    if doc_type == "other":
        return Decision("rejected", ["Dokumen bukan nota atau faktur"], classifier_conf)
    if classifier_conf < classifier_threshold:
        reasons.append(f"Jenis dokumen kurang yakin ({classifier_conf:.0%})")
    missing = [f for f in REQUIRED_FIELDS if not ex.field(f).present]
    if not ex.line_items:
        missing.append("line_items")
    if missing:
        reasons.append("Field wajib kosong: " + ", ".join(missing))
    for fd in findings:
        # Missing required fields are already reported above.
        if fd.status in ("fail", "warning") and fd.rule != "required_fields_present":
            reasons.append(fd.detail or fd.rule)
    low = sorted((c, f) for f, c in field_conf.items() if c < field_threshold)
    if low:
        reasons.append("Keyakinan rendah: " + ", ".join(f"{f} ({c:.0%})" for c, f in low[:6]))
    for flag in flags or []:
        reasons.append(flag)
    doc_conf = min([classifier_conf, *field_conf.values()]) if field_conf else classifier_conf
    return Decision("auto_approved" if not reasons else "needs_review", reasons, round(float(doc_conf), 4))
