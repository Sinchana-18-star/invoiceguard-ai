import pandas as pd
import streamlit as st

from components.common import get_ctx, inr, status_badge
from core import service

ctx = get_ctx()
st.title("Dashboard")
m = service.metrics(ctx)

c = st.columns(6)
c[0].metric("Invoices received", m["total"])
c[1].metric("Verified by checker", m["verified"])
c[2].metric("Pending approval", m["pending"])
c[3].metric("Escalated", m["escalated"])
c[4].metric("Rejected", m["rejected"])
c[5].metric("Verification success rate", f"{m['success_rate']:.0%}")

left, right = st.columns([3, 2])
with left:
    st.subheader("Recent invoices")
    invoices = service.list_invoices(ctx)[:15]
    if not invoices:
        st.info("No invoices yet. Go to **Employee - Upload** to submit one.")
    for inv in invoices:
        risk = ((inv["checker"] or {}).get("risk") or {})
        risk_txt = f" · risk {risk['score']}" if risk else ""
        st.markdown(f"{status_badge(inv['status'])} **{inv['id']}** · {inv['supplier_name'] or inv['file_name']} · "
                    f"₹{inr(inv['grand_total'])}{risk_txt} · uploaded by `{inv['uploader_id']}`")
with right:
    st.subheader("Recent activity")
    events = ctx.audit.get_recent_events(20)
    if events:
        df = pd.DataFrame([{"#": e["seq"], "time (UTC)": e["timestamp"][11:19], "event": e["event_type"],
                            "invoice": e["invoice_id"], "actor": e["actor"]} for e in events])
        st.dataframe(df, hide_index=True, width="stretch")
