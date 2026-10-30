import altair as alt
import pandas as pd
import streamlit as st

from core.db import Status
from ui import data
from ui.access import PAGES, require, sees_all_invoices
from ui.components.badges import STATUS_STYLE, status_label, verification
from ui.components.kpi import kpi_card
from ui.components.shell import page_header
from ui.components.states import empty_state
from ui.components.workflow import pipeline_svg
from ui.format import money, render_svg_markup

user = page_header("dashboard", "Overview", "Financial operations command centre. All figures come from the "
                                            "invoice database and audit log.")
require(user, "dashboard")

m = data.metrics()
k = st.columns(6)
cards = [("Total invoices", str(m["total"]), "inbox", "accent"),
         ("Verified invoices", str(m["verified"]), "check", "success"),
         ("Pending approvals", str(m["pending"]), "clock", "warning"),
         ("Rejected", str(m["rejected"]), "x", "danger"),
         ("Escalated", str(m["escalated"]), "alert", "warning"),
         ("Verification success rate", f"{m['success_rate']:.0%}", "percent", "accent")]
for col, (title, value, icon, tint) in zip(k, cards):
    with col:
        kpi_card(title, value, icon, tint)
st.caption("No period-over-period comparison is shown because the system has no historical baseline yet. "
           "\"Verified\" = invoices whose independent checker passed.")

invoices = data.invoices_for(user)
if not invoices:
    empty_state("No invoices yet", "Upload one from the Employee Workspace to populate the dashboard.")
    st.stop()

palette = {label: c for label, c in [("Approved", "#23865B"), ("Pending approval", "#D99A32"), ("Rejected", "#CC5151"),
                                     ("Escalated", "#B7791F"), ("Blocked", "#8B3A3A"), ("Processing", "#3978C5"),
                                     ("Received", "#718096")]}
left, right = st.columns([3, 2], gap="large")
with left:
    st.html('<div class="ig-section-title">Invoice processing activity</div>')
    df = pd.DataFrame([{"day": pd.Timestamp(i["created_at"]).strftime("%d %b"), "sort": pd.Timestamp(i["created_at"]).strftime("%Y%m%d"),
                        "status": status_label(i["status"])} for i in invoices])
    trend = df.groupby(["sort", "day", "status"]).size().reset_index(name="invoices")
    chart = (alt.Chart(trend).mark_bar(size=38, cornerRadiusTopLeft=2, cornerRadiusTopRight=2)
             .encode(x=alt.X("day:O", title="Received (day, UTC)", sort=alt.SortField("sort"), axis=alt.Axis(labelAngle=0)),
                     y=alt.Y("invoices:Q", title="Invoices", stack=True, axis=alt.Axis(tickMinStep=1)),
                     color=alt.Color("status:N", scale=alt.Scale(domain=list(palette), range=list(palette.values())),
                                     legend=alt.Legend(orient="bottom", title=None)),
                     tooltip=["day:O", "status:N", "invoices:Q"]).properties(height=260))
    st.altair_chart(chart, width="stretch")
with right:
    st.html('<div class="ig-section-title">Status distribution</div>')
    by_status = (m["by_status"] if sees_all_invoices(user)
                 else pd.Series([i["status"] for i in invoices]).value_counts().to_dict())
    dist = pd.DataFrame([{"status": STATUS_STYLE.get(s, (s,))[0], "invoices": n} for s, n in by_status.items()])
    donut = (alt.Chart(dist).mark_arc(innerRadius=60)
             .encode(theta="invoices:Q",
                     color=alt.Color("status:N", scale=alt.Scale(domain=list(palette), range=list(palette.values())),
                                     legend=alt.Legend(orient="right", title=None)),
                     tooltip=["status:N", "invoices:Q"]).properties(height=260))
    st.altair_chart(donut, width="stretch")

st.html('<div class="ig-section-title">Verification pipeline overview</div>')
counts = {s: sum(1 for i in invoices if i["status"] == s) for s in STATUS_STYLE}
in_flight = counts[Status.RECEIVED] + counts[Status.PROCESSING]
overview = [
    {"key": "intake", "name": "Invoice Intake", "state": "completed", "caption": f"{len(invoices)} received"},
    {"key": "extraction", "name": "Document Extraction", "state": "active" if in_flight else "completed",
     "caption": f"{in_flight} in progress"},
    {"key": "validation", "name": "Business Validation", "state": "failed" if counts[Status.BLOCKED] else "completed",
     "caption": f"{counts[Status.BLOCKED]} blocked"},
    {"key": "agentic", "name": "Agentic Workflow", "state": "completed", "caption": "record + ledger"},
    {"key": "checker", "name": "Independent Checker", "state": "completed",
     "caption": f"{sum(1 for i in invoices if (i['checker'] or {}).get('passed'))} passed"},
    {"key": "human", "name": "Human Approval", "state": "escalated" if counts[Status.ESCALATED] else
     "active" if counts[Status.AWAITING_APPROVAL] else "completed",
     "caption": f"{counts[Status.AWAITING_APPROVAL]} waiting · {counts[Status.ESCALATED]} escalated"},
    {"key": "final", "name": "Finalization", "state": "completed",
     "caption": f"{counts[Status.APPROVED]} approved · {counts[Status.REJECTED]} rejected"},
]
render_svg_markup(pipeline_svg(overview))
st.page_link(PAGES["workflow"][0], label="Open the per-invoice pipeline", icon=":material/arrow_forward:")


@st.fragment(run_every="20s")
def recent_activity() -> None:
    st.html('<div class="ig-section-title">Recent invoice activity <span class="ig-subtitle">(refreshes every 20s)</span></div>')
    rows = [{"Invoice ID": i["id"], "Invoice": i["invoice_number"] or i["file_name"], "Supplier": i["supplier_name"] or "-",
             "Amount": money(i["grand_total"]), "Status": status_label(i["status"]), "Verification": verification(i)[0],
             "Updated": pd.Timestamp(i["updated_at"]).strftime("%d %b %Y, %H:%M")} for i in data.invoices_for(user)[:15]]
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch",
                 column_config={"Amount": st.column_config.TextColumn(help="Indian digit grouping, exact Decimal")})


recent_activity()
