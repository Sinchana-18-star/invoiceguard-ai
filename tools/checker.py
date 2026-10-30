"""Independent deterministic checker.

Pure Python Decimal arithmetic plus read-only database lookups. It never calls the LLM, never modifies
the extracted data and never approves anything: passing only makes an invoice *eligible* for a human.
Running it twice on the same data always gives the same answer, so it is never retried.
"""
from __future__ import annotations

from decimal import Decimal

from sqlalchemy.orm import Session

from core.config import WorkflowSpec
from tools.gst import expected_tax_split, money, state_code, validate_gstin
from tools.models import CheckerResult, ExtractedInvoice
from tools.three_way_match import three_way_match

ZERO = Decimal(0)


def run_checker(session: Session, invoice: ExtractedInvoice, spec: WorkflowSpec) -> CheckerResult:
    tol = spec.thresholds.rounding_tolerance_inr
    reasons, evidence, warnings = [], [], []
    calc: dict[str, str] = {}

    def compare(label: str, stated: Decimal | None, expected: Decimal) -> None:
        expected = money(expected)
        calc[label] = str(expected)
        if stated is None:
            reasons.append(f"{label.upper()}_MISSING: invoice does not state {label}; calculated {expected}")
        elif abs(stated - expected) > tol:
            reasons.append(f"{label.upper()}_MISMATCH: invoice says {stated}, calculated {expected} "
                           f"(difference {money(stated - expected)}, tolerance {tol})")
        else:
            evidence.append(f"{label}: stated {stated} = calculated {expected} (within {tol})")

    # GSTINs
    for problem in validate_gstin(invoice.supplier_gstin):
        reasons.append(f"SUPPLIER_GSTIN_INVALID: {problem}")
    buyer_gstin = invoice.buyer_gstin or spec.company.gstin
    if invoice.buyer_gstin and invoice.buyer_gstin.upper() != spec.company.gstin:
        warnings.append(f"Buyer GSTIN {invoice.buyer_gstin} is not our company GSTIN {spec.company.gstin}")
    intra = state_code(invoice.supplier_gstin) == state_code(buyer_gstin)
    evidence.append("Supply type: " + ("intra-state (CGST + SGST)" if intra else "inter-state (IGST)"))

    # Line items, subtotal, tax
    if not invoice.line_items:
        reasons.append("NO_LINE_ITEMS: no line items could be checked")
    valid_rates = set(spec.gst.valid_rates)
    subtotal, tax = ZERO, {"cgst": ZERO, "sgst": ZERO, "igst": ZERO}
    for n, line in enumerate(invoice.line_items, start=1):
        if line.quantity is None or line.unit_price is None or line.gst_rate is None:
            reasons.append(f"LINE_{n}_INCOMPLETE: quantity, unit price and GST rate are all required")
            continue
        taxable = line.quantity * line.unit_price
        if line.taxable_value is not None and abs(line.taxable_value - money(taxable)) > tol:
            reasons.append(f"LINE_{n}_AMOUNT_MISMATCH: {line.quantity} x {line.unit_price} = {money(taxable)}, "
                           f"invoice says {line.taxable_value}")
        if line.gst_rate not in valid_rates:
            reasons.append(f"LINE_{n}_GST_RATE_INVALID: {line.gst_rate}% is not a valid GST slab "
                           f"({', '.join(str(r) for r in sorted(valid_rates))})")
        subtotal += taxable
        for k, v in expected_tax_split(taxable, line.gst_rate, intra).items():
            tax[k] += v

    compare("subtotal", invoice.subtotal, subtotal)
    if intra:
        compare("cgst", invoice.cgst, tax["cgst"])
        compare("sgst", invoice.sgst, tax["sgst"])
        if invoice.igst not in (None, ZERO):
            reasons.append(f"IGST_ON_INTRA_STATE: IGST {invoice.igst} charged on an intra-state supply")
    else:
        compare("igst", invoice.igst, tax["igst"])
        if invoice.cgst not in (None, ZERO) or invoice.sgst not in (None, ZERO):
            reasons.append("CGST_SGST_ON_INTER_STATE: CGST/SGST charged on an inter-state supply")
    expected_total = money(subtotal) + money(tax["cgst"]) + money(tax["sgst"]) + money(tax["igst"])
    compare("grand_total", invoice.grand_total, expected_total)

    # Business value limit
    limit = spec.bounds.max_invoice_value_inr
    if invoice.grand_total is not None and invoice.grand_total > limit:
        reasons.append(f"VALUE_LIMIT_EXCEEDED: {invoice.grand_total} > {limit}")

    # Three-way match
    match = three_way_match(session, invoice, spec.thresholds.price_tolerance_pct)
    reasons += match["reasons"]
    evidence += match["evidence"]
    warnings += match["warnings"]

    return CheckerResult(passed=not reasons, reasons=reasons, evidence=evidence, calculated_values=calc,
                         warnings=warnings)
