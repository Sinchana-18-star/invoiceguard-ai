import pandas as pd
import streamlit as st
from sqlalchemy import select

from components.common import current_user, get_ctx, inr
from core import service
from core.db import GoodsReceipt, PurchaseOrder, Supplier

ctx = get_ctx()
user = current_user()
st.title("Suppliers, Purchase Orders & Goods Receipts")
st.caption("Records prefixed 'Demo' are fictional fixtures for the hackathon demo.")
editable = user.role == ctx.spec.approver
if not editable:
    st.info("Only accounts managers can add master data. You can view it.")

with ctx.Session() as s:
    suppliers = s.scalars(select(Supplier)).all()
    pos = s.scalars(select(PurchaseOrder)).all()
    grns = s.scalars(select(GoodsReceipt)).all()
    sup_rows = [{"Name": x.name, "GSTIN": x.gstin, "State": x.state_code} for x in suppliers]
    po_rows = [{"PO": p.po_number, "Supplier": p.supplier.name, "Item": i.description, "Qty": str(i.quantity),
                "Unit price (₹)": inr(i.unit_price), "GST %": str(i.gst_rate)} for p in pos for i in p.items]
    grn_rows = [{"GRN": g.grn_number, "PO": g.po.po_number, "Item": i.description, "Received": str(i.quantity_received)}
                for g in grns for i in g.items]
    po_numbers = [p.po_number for p in pos]
    gstins = [x.gstin for x in suppliers]

t1, t2, t3 = st.tabs(["Suppliers", "Purchase orders", "Goods receipts"])
with t1:
    st.dataframe(pd.DataFrame(sup_rows), hide_index=True, width="stretch")
    if editable:
        with st.form("add_supplier", clear_on_submit=True):
            name, gstin = st.text_input("Supplier name"), st.text_input("GSTIN")
            if st.form_submit_button("Add supplier"):
                try:
                    service.add_supplier(ctx, name, gstin)
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
ITEM_COLS = ["description", "quantity", "unit_price", "gst_rate"]
with t2:
    st.dataframe(pd.DataFrame(po_rows), hide_index=True, width="stretch")
    if editable and gstins:
        with st.form("add_po", clear_on_submit=True):
            po_no, sup = st.text_input("PO number"), st.selectbox("Supplier GSTIN", gstins)
            items = st.data_editor(pd.DataFrame(columns=ITEM_COLS), num_rows="dynamic", key="po_items")
            if st.form_submit_button("Add purchase order"):
                try:
                    service.add_purchase_order(ctx, po_no, sup, items.dropna().to_dict("records"))
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
with t3:
    st.dataframe(pd.DataFrame(grn_rows), hide_index=True, width="stretch")
    if editable and po_numbers:
        with st.form("add_grn", clear_on_submit=True):
            grn_no, po_no = st.text_input("GRN number"), st.selectbox("Against PO", po_numbers)
            items = st.data_editor(pd.DataFrame(columns=["description", "quantity_received"]), num_rows="dynamic",
                                   key="grn_items")
            if st.form_submit_button("Add goods receipt"):
                try:
                    service.add_goods_receipt(ctx, grn_no, po_no, items.dropna().to_dict("records"))
                    st.rerun()
                except Exception as e:
                    st.error(str(e))
