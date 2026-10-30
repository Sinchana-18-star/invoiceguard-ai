"""Explainable fraud-risk score (0-100).

Deterministic rules, each with fixed points and a plain-English reason, so a manager (or a judge) can see
exactly why an invoice scored what it did. The score never approves or rejects anything: a HIGH score
sends the invoice to manual review, a lower score is shown to the approving manager.
"""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.config import WorkflowSpec
from core.db import Invoice, Status, User
from tools.models import ExtractedInvoice
from tools.validator import parse_date

HIGH, MEDIUM = 60, 30


def _signal(code: str, points: int, detail: str) -> dict:
    return {"code": code, "points": points, "detail": detail}


def assess_risk(session: Session, inv: ExtractedInvoice, *, invoice_id: str, flags: list[str],
                validation: dict, checker: dict, spec: WorkflowSpec, ledger: dict | None = None) -> dict:
    signals = []
    reasons = " ".join(checker.get("reasons", []))
    warnings = [w["code"] for w in validation.get("warnings", [])]
    total = inv.grand_total
    gstin = (inv.supplier_gstin or "").upper()
    inv_date, due = parse_date(inv.invoice_date), parse_date(inv.due_date)

    if ledger and ledger.get("status") == "REGISTERED_ELSEWHERE":
        signals.append(_signal("DOUBLE_FINANCING", 70, "This invoice is already registered on the shared ledger "
                                                       "by another organisation"))
    if "PROMPT_INJECTION_SUSPECTED" in flags:
        signals.append(_signal("HIDDEN_INSTRUCTIONS", 40, "Document contains instructions aimed at an AI system"))
    if "POSSIBLE_DUPLICATE" in flags:
        signals.append(_signal("NEAR_DUPLICATE", 35, "Very similar to another invoice from the same supplier"))
    if "PRICE_MISMATCH" in reasons:
        signals.append(_signal("PRICE_INFLATION", 20, "Unit price differs from the purchase order"))
    if "QTY_EXCEEDS_RECEIPT" in reasons or "OVER_RECEIPT" in reasons:
        signals.append(_signal("BILLING_UNRECEIVED_GOODS", 20, "Invoiced quantity is more than was received"))
    if "SUPPLIER_NAME_DIFFERS" in warnings:
        signals.append(_signal("SUPPLIER_NAME_MISMATCH", 10, "Supplier name differs from the supplier master"))

    others = session.scalars(select(Invoice).where(
        Invoice.supplier_gstin == gstin, Invoice.id != invoice_id, Invoice.invoice_number.is_not(None),
        Invoice.status != Status.BLOCKED)).all() if gstin else []
    if gstin and not others:
        signals.append(_signal("NEW_SUPPLIER", 10, "First invoice from this supplier"))

    if total is not None:
        limits = [u.approval_limit for u in session.scalars(select(User).where(User.role == spec.approver)).all()
                  if u.approval_limit] + [spec.bounds.max_invoice_value_inr]
        near = [lim for lim in limits if lim * Decimal("0.95") <= total < lim]
        if near:
            signals.append(_signal("JUST_BELOW_LIMIT", 15, f"Total is within 5% below an approval limit of {min(near)}"))
        if total >= 10000 and total % 1000 == 0:
            signals.append(_signal("ROUND_AMOUNT", 5, "Suspiciously round total"))

        # Invoice splitting: several invoices on one PO in a short window that only together exceed a limit
        if inv_date and inv.po_number:
            window = [o for o in others if o.po_number == inv.po_number.strip() and o.grand_total is not None
                      and (d := parse_date(o.invoice_date)) and abs((d - inv_date).days) <= spec.thresholds.fuzzy_duplicate_days]
            combined = total + sum(o.grand_total for o in window)
            crossed = [lim for lim in limits if total < lim <= combined]
            if window and crossed:
                signals.append(_signal("POSSIBLE_SPLITTING", 25,
                                       f"{len(window) + 1} invoices on {inv.po_number} within "
                                       f"{spec.thresholds.fuzzy_duplicate_days} days add up to {combined}, above "
                                       f"the {min(crossed)} limit that each one stays under"))

    if inv_date and inv_date.weekday() >= 5:
        signals.append(_signal("WEEKEND_DATE", 5, f"Invoice dated on a {inv_date.strftime('%A')}"))
    if inv_date and due and timedelta(0) <= due - inv_date <= timedelta(days=3):
        signals.append(_signal("URGENT_PAYMENT_TERMS", 10, f"Payment demanded within {(due - inv_date).days} day(s)"))

    score = min(100, sum(s["points"] for s in signals))
    level = "HIGH" if score >= HIGH else "MEDIUM" if score >= MEDIUM else "LOW"
    return {"score": score, "level": level, "signals": sorted(signals, key=lambda s: -s["points"])}
