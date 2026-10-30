"""Input and business validation. Errors block the invoice; warnings and flags go to the human reviewer."""
from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import WorkflowSpec
from core.db import Invoice, Status, Supplier
from tools import injection_guard
from tools.gst import validate_gstin
from tools.models import MANDATORY_FIELDS, ExtractedInvoice, Issue, ValidationResult

DATE_FORMATS = ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%d.%m.%Y", "%Y/%m/%d", "%d-%m-%y", "%d/%m/%y",
                "%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y", "%d %b, %Y", "%d %B, %Y")


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(" ".join(value.strip().split()), fmt).date()
        except ValueError:
            continue
    return None


def levenshtein(a: str, b: str) -> int:
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        cur = [i]
        for j, cb in enumerate(b, start=1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        prev = cur
    return prev[-1]


def validate(session: Session, inv: ExtractedInvoice, *, raw_text: str, spec: WorkflowSpec, invoice_id: str,
             file_hash: str | None, today: date | None = None) -> ValidationResult:
    errors: list[Issue] = []
    warnings: list[Issue] = []
    flags: list[str] = []
    today = today or date.today()

    # 1. Required fields
    for f in MANDATORY_FIELDS:
        if getattr(inv, f) in (None, ""):
            errors.append(Issue(code="MISSING_FIELD", field=f, message=f"Required field '{f}' is missing"))
    if not inv.line_items:
        errors.append(Issue(code="MISSING_FIELD", field="line_items", message="No line items found"))

    # 2-3. Invoice number and dates
    if inv.invoice_number and len(inv.invoice_number) < 3:
        errors.append(Issue(code="INVALID_INVOICE_NUMBER", field="invoice_number",
                            message=f"Invoice number '{inv.invoice_number}' is too short"))
    inv_date = parse_date(inv.invoice_date)
    if inv.invoice_date and inv_date is None:
        errors.append(Issue(code="INVALID_DATE", field="invoice_date",
                            message=f"Invoice date '{inv.invoice_date}' is not a recognised date"))
    elif inv_date and inv_date > today:
        errors.append(Issue(code="FUTURE_DATE", field="invoice_date", message=f"Invoice date {inv_date} is in the future"))
    due = parse_date(inv.due_date)
    if inv_date and due and due < inv_date:
        warnings.append(Issue(code="DUE_BEFORE_INVOICE", field="due_date", message="Due date is before the invoice date"))

    # 4-5. GSTIN format and supplier master
    supplier = None
    if inv.supplier_gstin:
        for problem in validate_gstin(inv.supplier_gstin):
            errors.append(Issue(code="INVALID_GSTIN", field="supplier_gstin", message=problem))
        supplier = session.scalar(select(Supplier).where(Supplier.gstin == inv.supplier_gstin.upper()))
        if supplier is None:
            errors.append(Issue(code="SUPPLIER_NOT_FOUND", field="supplier_gstin",
                                message=f"No registered supplier with GSTIN {inv.supplier_gstin}"))
        elif inv.supplier_name and inv.supplier_name.strip().casefold() != supplier.name.casefold():
            warnings.append(Issue(code="SUPPLIER_NAME_DIFFERS", field="supplier_name",
                                  message=f"Invoice says '{inv.supplier_name}', supplier master says '{supplier.name}'"))

    # 6. Duplicates
    if inv.supplier_gstin and inv.invoice_number:
        exact = session.scalar(select(Invoice).where(
            Invoice.supplier_gstin == inv.supplier_gstin.upper(),
            Invoice.invoice_number == inv.invoice_number.strip(),
            Invoice.id != invoice_id))
        if exact is not None:
            errors.append(Issue(code="DUPLICATE_INVOICE", field="invoice_number",
                                message=f"Invoice {inv.invoice_number} from {inv.supplier_gstin} already exists "
                                        f"as {exact.id} (status {exact.status})"))
    if file_hash:
        same_file = session.scalar(select(Invoice).where(Invoice.file_hash == file_hash, Invoice.id != invoice_id,
                                                         Invoice.status != Status.BLOCKED))
        if same_file is not None:
            errors.append(Issue(code="DUPLICATE_FILE", message=f"Identical file already submitted as {same_file.id}"))
    if supplier is not None and inv.invoice_number:
        others = session.scalars(select(Invoice).where(Invoice.supplier_gstin == supplier.gstin, Invoice.id != invoice_id,
                                                       Invoice.invoice_number.is_not(None))).all()
        t = spec.thresholds
        for other in others:
            if other.invoice_number == inv.invoice_number.strip():
                continue
            near_number = levenshtein(other.invoice_number, inv.invoice_number.strip()) <= t.fuzzy_invoice_number_distance
            near_amount = (other.grand_total is not None and inv.grand_total is not None and other.grand_total > 0
                           and abs(other.grand_total - inv.grand_total) / other.grand_total * 100 <= t.fuzzy_amount_tolerance_pct)
            other_date = parse_date(other.invoice_date)
            near_date = bool(other_date and inv_date and abs((other_date - inv_date).days) <= t.fuzzy_duplicate_days)
            # Sequential numbers from one supplier are normal, so a near number alone is not enough:
            # the amount must also be similar, together with a near number or a near date.
            if near_amount and (near_number or near_date):
                why = ("similar invoice number and amount" if near_number
                       else f"similar amount within {t.fuzzy_duplicate_days} days")
                warnings.append(Issue(code="POSSIBLE_DUPLICATE", field="invoice_number",
                                      message=f"Possible duplicate of {other.invoice_number} ({other.id}): {why}"))
                if "POSSIBLE_DUPLICATE" not in flags:
                    flags.append("POSSIBLE_DUPLICATE")

    # 7-9. Quantities, prices, impossible values
    for n, line in enumerate(inv.line_items, start=1):
        if not line.description:
            errors.append(Issue(code="INVALID_LINE", field=f"line_items.{n-1}.description", message=f"Line {n} has no description"))
        if line.quantity is None or line.quantity <= 0:
            errors.append(Issue(code="INVALID_QUANTITY", field=f"line_items.{n-1}.quantity",
                                message=f"Line {n} quantity must be a positive number (got {line.quantity})"))
        if line.unit_price is None or line.unit_price < 0:
            errors.append(Issue(code="INVALID_UNIT_PRICE", field=f"line_items.{n-1}.unit_price",
                                message=f"Line {n} unit price must be zero or more (got {line.unit_price})"))
    for f in ("subtotal", "cgst", "sgst", "igst", "grand_total"):
        v: Decimal | None = getattr(inv, f)
        if v is not None and v < 0:
            errors.append(Issue(code="NEGATIVE_AMOUNT", field=f, message=f"{f} cannot be negative ({v})"))

    # 10. Suspicious content (flag, never auto-act on it)
    hits = injection_guard.scan(raw_text)
    if hits:
        flags.append("PROMPT_INJECTION_SUSPECTED")
        warnings.append(Issue(code="SUSPICIOUS_CONTENT",
                              message="Instruction-like text found in the document and ignored: " + "; ".join(hits)))

    # 11. Business value limit (budget bound)
    limit = spec.bounds.max_invoice_value_inr
    if inv.grand_total is not None and inv.grand_total > limit:
        errors.append(Issue(code="VALUE_LIMIT_EXCEEDED", field="grand_total",
                            message=f"Invoice total {inv.grand_total} exceeds the configured limit of {limit}"))

    return ValidationResult(passed=not errors, errors=errors, warnings=warnings, flags=flags)
