"""Action tool: normalise the validated extraction and build the invoice record in the database.

It formats identifiers and dates but never changes an amount, quantity, price or rate.
"""
from __future__ import annotations

import json

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from core.db import Invoice, InvoiceItem, Supplier
from tools.models import ExtractedInvoice
from tools.validator import parse_date


def build_invoice_record(session: Session, invoice_id: str, inv: ExtractedInvoice) -> dict:
    record = session.get(Invoice, invoice_id)
    if record is None:
        return {"ok": False, "reason": f"INVOICE_ROW_MISSING: {invoice_id}"}
    gstin = (inv.supplier_gstin or "").strip().upper()
    supplier = session.scalar(select(Supplier).where(Supplier.gstin == gstin))
    inv_date = parse_date(inv.invoice_date)

    record.invoice_number = (inv.invoice_number or "").strip()
    record.supplier_gstin = gstin
    record.supplier_id = supplier.id if supplier else None
    record.supplier_name = supplier.name if supplier else inv.supplier_name
    record.invoice_date = inv_date.isoformat() if inv_date else None
    record.po_number = (inv.po_number or "").strip()
    record.grand_total = inv.grand_total
    record.items.clear()
    for n, line in enumerate(inv.line_items, start=1):
        record.items.append(InvoiceItem(line_no=n, description=(line.description or "").strip(), quantity=line.quantity,
                                        unit_price=line.unit_price, gst_rate=line.gst_rate,
                                        taxable_value=line.taxable_value))
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        return {"ok": False, "reason": f"DUPLICATE_INVOICE: {gstin}/{inv.invoice_number} already recorded (database constraint)"}
    return {"ok": True, "record": {
        "invoice_id": invoice_id, "invoice_number": record.invoice_number, "supplier_gstin": gstin,
        "supplier_name": record.supplier_name, "invoice_date": record.invoice_date, "po_number": record.po_number,
        "grand_total": str(record.grand_total) if record.grand_total is not None else None,
        "line_count": len(inv.line_items),
    }}


def dumps(obj) -> str:
    return json.dumps(obj, default=str, ensure_ascii=False)
