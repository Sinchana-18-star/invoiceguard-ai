"""Pydantic models shared by the extraction, validation and checking tools."""
from __future__ import annotations

from decimal import Decimal

from pydantic import BaseModel, Field

MANDATORY_FIELDS = ("invoice_number", "supplier_name", "supplier_gstin", "invoice_date", "po_number", "grand_total")


class LineItem(BaseModel):
    description: str | None = None
    quantity: Decimal | None = None
    unit_price: Decimal | None = None
    gst_rate: Decimal | None = None
    taxable_value: Decimal | None = None


class ExtractedInvoice(BaseModel):
    """Exactly what the document says. Missing values stay None; nothing is inferred or corrected."""
    invoice_number: str | None = None
    supplier_name: str | None = None
    supplier_gstin: str | None = None
    buyer_name: str | None = None
    buyer_gstin: str | None = None
    invoice_date: str | None = None
    due_date: str | None = None
    po_number: str | None = None
    line_items: list[LineItem] = Field(default_factory=list)
    subtotal: Decimal | None = None
    cgst: Decimal | None = None
    sgst: Decimal | None = None
    igst: Decimal | None = None
    grand_total: Decimal | None = None

    def has_any_field(self) -> bool:
        return any(getattr(self, f) is not None for f in MANDATORY_FIELDS) or bool(self.line_items)


class ExtractionResult(BaseModel):
    strategy: str
    available: bool
    invoice: ExtractedInvoice = Field(default_factory=ExtractedInvoice)
    confidence: dict[str, float] = Field(default_factory=dict)
    raw_text: str = ""
    notes: list[str] = Field(default_factory=list)

    @property
    def overall_confidence(self) -> float:
        return overall_confidence(self.confidence)

    @classmethod
    def unavailable(cls, strategy: str, note: str) -> "ExtractionResult":
        return cls(strategy=strategy, available=False, notes=[note])


def overall_confidence(confidence: dict[str, float]) -> float:
    """Mean confidence of the mandatory fields + line items that were found (missing fields are a
    validation problem, not an extraction-quality signal)."""
    keys = [*MANDATORY_FIELDS, "line_items"]
    found = [confidence[k] for k in keys if confidence.get(k, 0) > 0]
    return round(sum(found) / len(found), 4) if found else 0.0


class Issue(BaseModel):
    code: str
    message: str
    field: str | None = None


class ValidationResult(BaseModel):
    passed: bool
    errors: list[Issue] = Field(default_factory=list)
    warnings: list[Issue] = Field(default_factory=list)
    flags: list[str] = Field(default_factory=list)


class CheckerResult(BaseModel):
    passed: bool
    reasons: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)
    calculated_values: dict[str, str] = Field(default_factory=dict)
    warnings: list[str] = Field(default_factory=list)
