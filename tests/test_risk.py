"""Fraud-risk score: explainable signals and HIGH-risk escalation."""
from __future__ import annotations

from conftest import FakeStrategy, result_from, submit, valid_intra_fields
from core import service
from core.db import Status
from tools.models import ExtractedInvoice
from tools.risk import assess_risk


def score(ctx, fields, flags=(), validation=None, checker=None, invoice_id="INV-NEW"):
    with ctx.Session() as s:
        return assess_risk(s, ExtractedInvoice.model_validate(fields), invoice_id=invoice_id, flags=list(flags),
                           validation=validation or {}, checker=checker or {}, spec=ctx.spec)


def codes(risk):
    return {s["code"] for s in risk["signals"]}


def test_clean_invoice_from_new_supplier_is_low(make_ctx):
    risk = score(make_ctx(), valid_intra_fields())
    assert risk["level"] == "LOW" and codes(risk) == {"NEW_SUPPLIER"}


def test_signals_are_explained(make_ctx):
    risk = score(make_ctx(), valid_intra_fields(invoice_date="2026-10-18", due_date="2026-10-19"),
                 flags=["POSSIBLE_DUPLICATE"], checker={"reasons": ["PRICE_MISMATCH: line 1 ..."]})
    assert {"NEAR_DUPLICATE", "PRICE_INFLATION", "WEEKEND_DATE", "URGENT_PAYMENT_TERMS"} <= codes(risk)
    assert risk["level"] == "HIGH" and all(s["detail"] for s in risk["signals"])


def test_just_below_approval_limit(make_ctx):
    risk = score(make_ctx(), valid_intra_fields(grand_total="98500.00"))  # mgr_arjun's limit is 1,00,000
    assert "JUST_BELOW_LIMIT" in codes(risk)


def test_invoice_splitting_detected(make_ctx):
    ctx = make_ctx({"fake": FakeStrategy(result_from(valid_intra_fields()))})
    base = dict(subtotal="50000.00", cgst="4500.00", sgst="4500.00", grand_total="59000.00",
                line_items=[{"description": "Steel Bolts M8", "quantity": "400", "unit_price": "125.00", "gst_rate": "18"}])
    ctx.strategies["fake"].result = result_from(valid_intra_fields(invoice_number="DSW-S-1", **base))
    submit(ctx)
    risk = score(ctx, valid_intra_fields(invoice_number="DSW-S-2", invoice_date="2026-10-22", **base))
    assert "POSSIBLE_SPLITTING" in codes(risk)  # 59,000 + 59,000 crosses the 1,00,000 limit


def test_high_risk_invoice_is_escalated_not_sent_for_approval(make_ctx):
    ctx = make_ctx({"fake": FakeStrategy(result_from(valid_intra_fields()))})
    submit(ctx)
    # near-duplicate (35) + weekend date (5) + 1-day payment terms (10) + supplier name mismatch (10) = 60
    ctx.strategies["fake"].result = result_from(valid_intra_fields(
        invoice_number="DSW-T-00O1", invoice_date="2026-10-18", due_date="2026-10-19", supplier_name="Demo Steel Works"))
    inv = submit(ctx)
    assert inv["checker"]["passed"] is True
    assert inv["checker"]["risk"]["level"] == "HIGH"
    assert inv["status"] == Status.ESCALATED and inv["escalation_reason"].startswith("FRAUD_RISK_HIGH")
    released = service.decide(ctx, inv["id"], "mgr_priya", "release", reason="Confirmed with supplier by phone")
    assert released["status"] == Status.AWAITING_APPROVAL
