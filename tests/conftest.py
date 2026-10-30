from __future__ import annotations

import sys
import uuid
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from core import service  # noqa: E402
from core.context import AppContext  # noqa: E402
from core.demo_data import SUPPLIER_A_GSTIN, SUPPLIER_B_GSTIN, seed_demo_data  # noqa: E402
from tools.models import ExtractedInvoice, ExtractionResult  # noqa: E402


def valid_intra_fields(**overrides) -> dict:
    """Correct intra-state invoice against demo PO-1001 / GRN-1001: 3300 + 18% GST = 3894."""
    fields = {
        "invoice_number": "DSW-T-0001", "supplier_name": "Demo Steel Works Pvt Ltd", "supplier_gstin": SUPPLIER_A_GSTIN,
        "buyer_name": "Demo Buyer Pvt Ltd", "invoice_date": "2026-10-20", "po_number": "PO-1001",
        "line_items": [
            {"description": "Steel Bolts M8", "quantity": "200", "unit_price": "12.50", "gst_rate": "18", "taxable_value": "2500.00"},
            {"description": "Hex Nuts M8", "quantity": "200", "unit_price": "4.00", "gst_rate": "18", "taxable_value": "800.00"},
        ],
        "subtotal": "3300.00", "cgst": "297.00", "sgst": "297.00", "grand_total": "3894.00",
    }
    fields.update(overrides)
    return fields


def valid_inter_fields(**overrides) -> dict:
    """Correct inter-state invoice against demo PO-2001: 197600 + 18% IGST = 233168."""
    fields = {
        "invoice_number": "DMS-T-0001", "supplier_name": "Demo Motion Systems Pvt Ltd", "supplier_gstin": SUPPLIER_B_GSTIN,
        "invoice_date": "2026-10-20", "po_number": "PO-2001",
        "line_items": [
            {"description": "Servo Motor 750W", "quantity": "8", "unit_price": "18500.00", "gst_rate": "18"},
            {"description": "Motor Controller", "quantity": "8", "unit_price": "6200.00", "gst_rate": "18"},
        ],
        "subtotal": "197600.00", "igst": "35568.00", "grand_total": "233168.00",
    }
    fields.update(overrides)
    return fields


def result_from(fields: dict, conf: float = 0.97, strategy: str = "fake", raw_text: str = "demo invoice text") -> ExtractionResult:
    invoice = ExtractedInvoice.model_validate(fields)
    confidence = {k: conf for k, v in fields.items() if v not in (None, [], "")}
    return ExtractionResult(strategy=strategy, available=True, invoice=invoice, confidence=confidence, raw_text=raw_text)


class FakeStrategy:
    """Returns a fixed ExtractionResult and counts how often it was called."""
    def __init__(self, result: ExtractionResult):
        self.result, self.calls = result, 0

    def __call__(self, path):
        self.calls += 1
        return self.result


@pytest.fixture(autouse=True)
def _isolated_env(monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    monkeypatch.delenv("INVOICEGUARD_ENABLE_LLM", raising=False)
    monkeypatch.delenv("INVOICEGUARD_WEBHOOK_URL", raising=False)
    # The blockchain ledger has its own tests (test_ledger.py); keep the other tests fast and offline.
    monkeypatch.setenv("INVOICEGUARD_LEDGER", "off")


@pytest.fixture
def make_ctx(tmp_path):
    created = []

    def _make(strategies: dict | None = None, data_dir: Path | None = None) -> AppContext:
        order = list(strategies) if strategies else None
        ctx = AppContext(data_dir=data_dir or tmp_path / "data", strategies=strategies, strategy_order=order)
        seed_demo_data(ctx)
        created.append(ctx)
        return ctx

    yield _make
    for ctx in created:
        try:
            ctx.close()
        except Exception:
            pass


def submit(ctx: AppContext, uploader: str = "emp_asha", name: str = "invoice.pdf") -> dict:
    """Submit unique bytes (the fake strategies ignore the file content)."""
    return service.submit_invoice(ctx, uploader, name, f"%PDF-test {uuid.uuid4()}".encode())


def events(ctx: AppContext, invoice_id: str) -> list[str]:
    return [e["event_type"] for e in ctx.audit.get_invoice_history(invoice_id)]
