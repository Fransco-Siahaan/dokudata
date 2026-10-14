"""Extraction schema (PRD section 9) shared by every extractor, the API and evaluation."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

DocType = Literal["receipt", "invoice", "other"]
DOC_TYPES: list[str] = ["receipt", "invoice", "other"]

TEXT_FIELDS = ["vendor_name", "vendor_tax_id", "document_number", "payment_method", "currency"]
DATE_FIELDS = ["issue_date", "due_date"]
AMOUNT_FIELDS = ["subtotal", "discount", "tax_amount", "total"]
HEADER_FIELDS = [
    "vendor_name",
    "vendor_tax_id",
    "document_number",
    "issue_date",
    "due_date",
    "currency",
    "subtotal",
    "discount",
    "tax_amount",
    "total",
    "payment_method",
]
REQUIRED_FIELDS = ["vendor_name", "issue_date", "currency", "total"]
# Line items are required too (PRD 9.1), checked separately because they are a list.


class FieldValue(BaseModel):
    value: Any = None
    confidence: float | None = None
    source: str | None = None
    bbox: list[float] | None = None
    page: int | None = None
    raw: str | None = None  # text as it appears in the document, before normalisation

    @property
    def present(self) -> bool:
        return self.value is not None and self.value != ""


class LineItem(BaseModel):
    description: str | None = None
    qty: float | None = None
    unit_price: float | None = None
    amount: float | None = None
    confidence: float | None = None
    bbox: list[float] | None = None
    page: int | None = None


class Extraction(BaseModel):
    vendor_name: FieldValue = Field(default_factory=FieldValue)
    vendor_tax_id: FieldValue = Field(default_factory=FieldValue)
    document_number: FieldValue = Field(default_factory=FieldValue)
    issue_date: FieldValue = Field(default_factory=FieldValue)
    due_date: FieldValue = Field(default_factory=FieldValue)
    currency: FieldValue = Field(
        default_factory=lambda: FieldValue(value="IDR", confidence=0.9, source="default")
    )
    subtotal: FieldValue = Field(default_factory=FieldValue)
    discount: FieldValue = Field(default_factory=FieldValue)
    tax_amount: FieldValue = Field(default_factory=FieldValue)
    total: FieldValue = Field(default_factory=FieldValue)
    payment_method: FieldValue = Field(default_factory=FieldValue)
    line_items: list[LineItem] = Field(default_factory=list)

    def field(self, name: str) -> FieldValue:
        value = getattr(self, name)
        assert isinstance(value, FieldValue)
        return value

    def values(self) -> dict[str, Any]:
        """Plain values, the shape used by ground truth, exports and comparisons."""
        out: dict[str, Any] = {name: self.field(name).value for name in HEADER_FIELDS}
        out["line_items"] = [
            {"description": li.description, "qty": li.qty, "unit_price": li.unit_price, "amount": li.amount}
            for li in self.line_items
        ]
        return out

    @classmethod
    def from_values(cls, values: dict[str, Any], source: str = "human") -> Extraction:
        """Build an extraction from plain values (used for reviewed data and tests)."""
        kwargs: dict[str, Any] = {}
        for name in HEADER_FIELDS:
            if name in values:
                kwargs[name] = FieldValue(value=values[name], confidence=1.0, source=source)
        kwargs["line_items"] = [LineItem(**li, confidence=1.0) for li in values.get("line_items") or []]
        return cls(**kwargs)


class ValidationFinding(BaseModel):
    rule: str
    status: Literal["pass", "warning", "fail", "skipped"]
    fields: list[str] = Field(default_factory=list)
    detail: str = ""


class DocumentResult(BaseModel):
    """Full pipeline output for one document (the JSON shape from PRD appendix 22.1)."""

    document_type: FieldValue
    extraction: Extraction
    validation: list[ValidationFinding]
    decision: Literal["auto_approved", "needs_review", "rejected"]
    decision_reasons: list[str] = Field(default_factory=list)
    document_confidence: float = 0.0
    engines: dict[str, str] = Field(default_factory=dict)
    timings_ms: dict[str, float] = Field(default_factory=dict)
    cost_usd: float = 0.0
    flags: list[str] = Field(default_factory=list)
    # Thresholds the decision used, so the review screen colours confidence the same way.
    thresholds: dict[str, float] = Field(default_factory=dict)
