"""Extracted-field tables with confidence indicators. Values are untrusted invoice text: escaped."""
from __future__ import annotations

import streamlit as st

from ui.components.badges import KIND_COLOR, confidence_kind
from ui.format import esc, money

MONEY_FIELDS = {"subtotal", "cgst", "sgst", "igst", "grand_total"}
LABELS = {
    "supplier_name": "Supplier name", "supplier_gstin": "Supplier GSTIN", "buyer_name": "Buyer name",
    "buyer_gstin": "Buyer GSTIN", "invoice_number": "Invoice number", "invoice_date": "Invoice date",
    "due_date": "Due date", "po_number": "PO number", "subtotal": "Taxable value (subtotal)", "cgst": "CGST",
    "sgst": "SGST / UTGST", "igst": "IGST", "grand_total": "Grand total",
}
SECTIONS = {
    "Supplier information": ["supplier_name", "supplier_gstin"],
    "Buyer information": ["buyer_name", "buyer_gstin"],
    "Invoice details": ["invoice_number", "invoice_date", "due_date", "po_number"],
    "Tax breakdown": ["cgst", "sgst", "igst"],
    "Financial summary": ["subtotal", "grand_total"],
}


def field_table(fields: dict, confidence: dict, keys: list[str], spec) -> None:
    rows = []
    for k in keys:
        value, conf = fields.get(k), confidence.get(k)
        if value in (None, ""):
            shown, conf_html, cls = '<span class="ig-missing">not on document</span>', "", ""
        else:
            shown = esc(money(value)) if k in MONEY_FIELDS else esc(value)
            kind = confidence_kind(conf, spec)
            cls = "ig-uncertain" if kind in ("warning", "danger") else ""
            conf_html = (f'<span class="ig-conf-dot" style="background:{KIND_COLOR[kind]}"></span>'
                         f'<span class="ig-num">{conf:.2f}</span>' if conf is not None else "")
        rows.append(f'<tr class="{cls}"><td class="ig-label">{esc(LABELS.get(k, k))}</td>'
                    f'<td class="ig-value">{shown}</td><td class="ig-conf">{conf_html}</td></tr>')
    st.html(f'<table class="ig-fields">{"".join(rows)}</table>')


def uncertain_fields(fields: dict, confidence: dict, spec) -> list[str]:
    return [LABELS.get(k, k) for k, v in fields.items()
            if k in LABELS and v not in (None, "") and confidence.get(k) is not None
            and confidence[k] < spec.thresholds.green_confidence]
