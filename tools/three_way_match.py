"""Three-way match: invoice vs purchase order (PO) vs goods receipt note (GRN). Read-only."""
from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from core.db import GoodsReceipt, PurchaseOrder, Supplier
from tools.models import ExtractedInvoice


def norm_desc(text: str | None) -> str:
    return re.sub(r"\s+", " ", (text or "").strip().casefold())


def three_way_match(session: Session, invoice: ExtractedInvoice, price_tolerance_pct: Decimal) -> dict:
    reasons, evidence, warnings = [], [], []
    po = session.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == (invoice.po_number or "").strip()))
    if po is None:
        return {"passed": False, "reasons": [f"PO_NOT_FOUND: purchase order '{invoice.po_number}' does not exist"],
                "evidence": [], "warnings": []}
    evidence.append(f"PO {po.po_number} found for supplier {po.supplier.name} ({po.supplier.gstin})")

    supplier = session.scalar(select(Supplier).where(Supplier.gstin == (invoice.supplier_gstin or "").upper()))
    if supplier is None or supplier.id != po.supplier_id:
        reasons.append(f"SUPPLIER_MISMATCH: invoice supplier GSTIN {invoice.supplier_gstin} is not the PO supplier "
                       f"{po.supplier.gstin}")
    else:
        evidence.append("Invoice supplier matches PO supplier")

    grns = session.scalars(select(GoodsReceipt).where(GoodsReceipt.po_id == po.id)).all()
    if not grns:
        reasons.append(f"GRN_NOT_FOUND: no goods receipt recorded against {po.po_number}")
        return {"passed": False, "reasons": reasons, "evidence": evidence, "warnings": warnings}
    evidence.append(f"GRN(s) found: {', '.join(g.grn_number for g in grns)}")

    received: dict[str, Decimal] = defaultdict(Decimal)
    for grn in grns:
        for item in grn.items:
            received[norm_desc(item.description)] += item.quantity_received
    po_items = {norm_desc(i.description): i for i in po.items}
    tolerance = price_tolerance_pct / Decimal(100)

    for n, line in enumerate(invoice.line_items, start=1):
        key = norm_desc(line.description)
        po_item = po_items.get(key)
        if po_item is None:
            reasons.append(f"ITEM_NOT_ON_PO: line {n} '{line.description}' is not on {po.po_number}")
            continue
        qty, price = line.quantity or Decimal(0), line.unit_price or Decimal(0)
        got = received.get(key, Decimal(0))
        if got > po_item.quantity:
            reasons.append(f"OVER_RECEIPT: line {n} received {got} > ordered {po_item.quantity}")
        if qty > got:
            reasons.append(f"QTY_EXCEEDS_RECEIPT: line {n} invoices {qty} but only {got} received")
        else:
            evidence.append(f"Line {n}: invoiced qty {qty} <= received {got} <= ordered {po_item.quantity}")
        low, high = po_item.unit_price * (1 - tolerance), po_item.unit_price * (1 + tolerance)
        if not (low <= price <= high):
            reasons.append(f"PRICE_MISMATCH: line {n} unit price {price} outside PO price {po_item.unit_price} "
                           f"+/-{price_tolerance_pct}%")
        else:
            evidence.append(f"Line {n}: unit price {price} within {price_tolerance_pct}% of PO price {po_item.unit_price}")
        if line.gst_rate is not None and line.gst_rate != po_item.gst_rate:
            warnings.append(f"Line {n}: GST rate {line.gst_rate}% differs from PO rate {po_item.gst_rate}%")

    return {"passed": not reasons, "reasons": reasons, "evidence": evidence, "warnings": warnings}
