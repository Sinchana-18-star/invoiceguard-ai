"""End-to-end runs on the generated demo PDFs with the real extraction strategies."""
from __future__ import annotations

from pathlib import Path

import pytest

from conftest import ROOT
from core import service
from core.db import Status

SAMPLES = ROOT / "samples"


@pytest.fixture(scope="module", autouse=True)
def _samples():
    if not (SAMPLES / "01_valid_intra_state.pdf").exists():
        import runpy
        runpy.run_path(str(ROOT / "scripts" / "make_sample_invoices.py"), run_name="__main__")


def submit_file(ctx, name, uploader="emp_asha"):
    path = SAMPLES / name
    return service.submit_invoice(ctx, uploader, name, path.read_bytes())


@pytest.mark.parametrize("name, status, reason_part", [
    ("01_valid_intra_state.pdf", Status.AWAITING_APPROVAL, None),
    ("02_valid_inter_state_large.pdf", Status.AWAITING_APPROVAL, None),
    ("03_arithmetic_mismatch.pdf", Status.ESCALATED, "CHECKER_FAILED_HIGH_CONFIDENCE"),
    ("04_missing_po_number.pdf", Status.BLOCKED, "po_number"),
    ("05_over_value_limit.pdf", Status.BLOCKED, "VALUE_LIMIT_EXCEEDED"),
    ("06_prompt_injection.pdf", Status.ESCALATED, "SUSPICIOUS_CONTENT"),
    ("07_price_mismatch.pdf", Status.ESCALATED, "PRICE_MISMATCH"),
    ("08_qty_exceeds_receipt.pdf", Status.ESCALATED, "QTY_EXCEEDS_RECEIPT"),
    ("10_table_layout_valid.pdf", Status.AWAITING_APPROVAL, None),  # other labels, ruled table, month-name date
])
def test_sample_pdf(make_ctx, name, status, reason_part):
    ctx = make_ctx()
    inv = submit_file(ctx, name)
    assert inv["status"] == status, inv
    assert inv["extraction_strategy"] == "pymupdf_text"
    if reason_part:
        text = " ".join(filter(None, [inv["failure_reason"], inv["escalation_reason"],
                                      " ".join((inv["checker"] or {}).get("reasons", []))]))
        assert reason_part in text


def test_duplicate_pdf_upload(make_ctx):
    ctx = make_ctx()
    assert submit_file(ctx, "01_valid_intra_state.pdf")["status"] == Status.AWAITING_APPROVAL
    again = submit_file(ctx, "01_valid_intra_state.pdf", uploader="emp_ravi")
    assert again["status"] == Status.BLOCKED and "DUPLICATE" in again["failure_reason"]


def test_scanned_image_falls_through_strategies(make_ctx):
    ctx = make_ctx()
    inv = submit_file(ctx, "09_scanned_valid.png")
    history = [e["event_type"] for e in ctx.audit.get_invoice_history(inv["id"])]
    assert history[1] == "EXTRACTION_RETRIED"  # the PDF text strategy cannot read an image
    # With Tesseract installed this reaches approval; without OCR/LLM it is escalated, never approved.
    assert inv["status"] in (Status.AWAITING_APPROVAL, Status.ESCALATED)
    assert inv["status"] != Status.APPROVED
