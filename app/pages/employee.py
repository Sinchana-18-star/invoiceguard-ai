from pathlib import Path

import streamlit as st

from components.common import current_user, get_ctx, inr, show_issues, status_badge
from core import service
from core.config import ROOT

ctx = get_ctx()
user = current_user()
st.title("Employee - Upload invoices")
st.caption("Upload a supplier invoice. It is extracted, validated and checked automatically, then sent to an "
           "accounts manager. Nothing is ever paid automatically.")

SAMPLES = ROOT / "samples"
tab_upload, tab_sample = st.tabs(["Upload a file", "Use a demo sample"])
submitted = None
with tab_upload:
    file = st.file_uploader("Invoice (PDF, PNG, JPG)", type=["pdf", "png", "jpg", "jpeg"])
    if st.button("Submit invoice", type="primary", disabled=file is None):
        with st.spinner("Running the verification workflow..."):
            try:
                submitted = service.submit_invoice(ctx, user.id, file.name, file.getvalue())
            except (ValueError, PermissionError) as e:
                st.error(str(e))
with tab_sample:
    samples = sorted(p.name for p in SAMPLES.glob("*") if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"})
    if not samples:
        st.info("Run `python scripts/make_sample_invoices.py` to create demo invoices.")
    else:
        choice = st.selectbox("Demo invoice (fictional)", samples)
        if st.button("Submit sample", type="primary"):
            with st.spinner("Running the verification workflow..."):
                submitted = service.submit_invoice(ctx, user.id, choice, (SAMPLES / choice).read_bytes())

if submitted:
    st.success(f"Submitted **{submitted['id']}** - status {submitted['status']}")
    st.markdown(status_badge(submitted["status"]))
    show_issues(submitted)
    st.page_link("pages/invoice_review.py", label="Open in Invoice Review", icon="🔍")
    st.session_state["review_invoice_id"] = submitted["id"]

st.divider()
st.subheader("My invoices")
mine = service.list_invoices(ctx, uploader_id=user.id)
if not mine:
    st.caption("You have not submitted any invoices yet.")
for inv in mine:
    with st.expander(f"{inv['id']} · {inv['invoice_number'] or Path(inv['file_name']).name} · {inv['status']}"):
        st.markdown(f"{status_badge(inv['status'])}  Supplier: **{inv['supplier_name'] or '-'}** · "
                    f"Total: **₹{inr(inv['grand_total'])}** · Extracted by `{inv['extraction_strategy'] or '-'}`")
        show_issues(inv)
        if inv["extracted"]:
            st.json(inv["extracted"], expanded=False)
