import pandas as pd
import streamlit as st
from sqlalchemy import select

from core import service
from core.config import DEFAULT_SPEC_PATH
from core.db import GoodsReceipt, PurchaseOrder, Supplier
from ui import data
from ui.access import require
from ui.components.shell import page_header
from ui.components.states import notice
from ui.format import md_safe, money
from ui.runtime import ROLE_LABELS, get_ctx

user = page_header("settings", "Governance", "Master data, users and the workflow specification.")
require(user, "settings")
ctx = get_ctx()
editable = user["role"] == ctx.spec.approver

tab_md, tab_users, tab_spec = st.tabs(["Suppliers, POs & GRNs", "Users & approval limits", "Workflow specification"])

with tab_md:
    st.caption("Records prefixed 'Demo' are fictional fixtures for the hackathon demo.")
    if not editable:
        notice("info", "Read-only", body="Only accounts managers can add master data.")
    with ctx.Session() as s:  # read-only listing (same query the previous master-data page used)
        suppliers = s.scalars(select(Supplier)).all()
        pos = s.scalars(select(PurchaseOrder)).all()
        grns = s.scalars(select(GoodsReceipt)).all()
        sup_rows = [{"Name": x.name, "GSTIN": x.gstin, "State": x.state_code} for x in suppliers]
        po_rows = [{"PO": p.po_number, "Supplier": p.supplier.name, "Item": i.description, "Qty": str(i.quantity),
                    "Unit price": money(i.unit_price), "GST %": str(i.gst_rate)} for p in pos for i in p.items]
        grn_rows = [{"GRN": g.grn_number, "PO": g.po.po_number, "Item": i.description,
                     "Received": str(i.quantity_received)} for g in grns for i in g.items]
        po_numbers, gstins = [p.po_number for p in pos], [x.gstin for x in suppliers]

    st.html('<div class="ig-section-title">Suppliers</div>')
    st.dataframe(pd.DataFrame(sup_rows), hide_index=True, width="stretch")
    if editable:
        with st.form("add_supplier", clear_on_submit=True):
            c1, c2 = st.columns(2)
            name, gstin = c1.text_input("Supplier name"), c2.text_input("GSTIN")
            if st.form_submit_button("Add supplier"):
                try:
                    service.add_supplier(ctx, name, gstin)
                    st.rerun()
                except Exception as e:  # noqa: BLE001 - e.g. invalid GSTIN checksum
                    st.error(md_safe(e))
    st.html('<div class="ig-section-title">Purchase orders</div>')
    st.dataframe(pd.DataFrame(po_rows), hide_index=True, width="stretch")
    if editable and gstins:
        with st.form("add_po", clear_on_submit=True):
            c1, c2 = st.columns(2)
            po_no, sup = c1.text_input("PO number"), c2.selectbox("Supplier GSTIN", gstins)
            items = st.data_editor(pd.DataFrame(columns=["description", "quantity", "unit_price", "gst_rate"]),
                                   num_rows="dynamic", key="po_items", width="stretch")
            if st.form_submit_button("Add purchase order"):
                try:
                    service.add_purchase_order(ctx, po_no, sup, items.dropna().to_dict("records"))
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(md_safe(e))
    st.html('<div class="ig-section-title">Goods receipts</div>')
    st.dataframe(pd.DataFrame(grn_rows), hide_index=True, width="stretch")
    if editable and po_numbers:
        with st.form("add_grn", clear_on_submit=True):
            c1, c2 = st.columns(2)
            grn_no, po_no = c1.text_input("GRN number"), c2.selectbox("Against PO", po_numbers)
            items = st.data_editor(pd.DataFrame(columns=["description", "quantity_received"]), num_rows="dynamic",
                                   key="grn_items", width="stretch")
            if st.form_submit_button("Add goods receipt"):
                try:
                    service.add_goods_receipt(ctx, grn_no, po_no, items.dropna().to_dict("records"))
                    st.rerun()
                except Exception as e:  # noqa: BLE001
                    st.error(md_safe(e))

with tab_users:
    st.dataframe(pd.DataFrame([{"User": u["id"], "Name": u["name"], "Role": ROLE_LABELS.get(u["role"], u["role"]),
                                "Approval limit": money(u["approval_limit"])} for u in data.users()]),
                 hide_index=True, width="stretch")
    st.caption("Users and limits are demo fixtures. There is no user-management API in this build.")

with tab_spec:
    st.caption(f"Loaded from {DEFAULT_SPEC_PATH.name} and validated with Pydantic at start-up. Read-only here; "
               "edit the file and restart to change it.")
    st.code(DEFAULT_SPEC_PATH.read_text(encoding="utf-8"), language="yaml")
