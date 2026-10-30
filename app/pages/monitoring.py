import json
import os

import pandas as pd
import streamlit as st

from ui import data
from ui.access import require
from ui.components.audit_timeline import friendly
from ui.components.kpi import kpi_card
from ui.components.shell import page_header
from ui.components.states import notice
from ui.format import when
from ui.runtime import get_ctx

user = page_header("monitoring", "Governance", "Health of the services the workflow depends on.")
require(user, "monitoring")
ctx = get_ctx()


@st.fragment(run_every="30s")
def health() -> None:
    chain = data.verify_chain()
    ledger = data.ledger_info()
    m = data.metrics()
    c = st.columns(4)
    with c[0]:
        kpi_card("Audit chain", "Intact" if chain["intact"] else f"Broken at #{chain['first_broken_seq']}",
                 "check" if chain["intact"] else "alert", "success" if chain["intact"] else "danger",
                 f"{chain['count']} events verified")
    with c[1]:
        kpi_card("Blockchain ledger", "Connected" if ledger["enabled"] else "Disabled",
                 "check" if ledger["enabled"] else "alert", "success" if ledger["enabled"] else "warning",
                 f"chain {ledger['chain_id']} · block {ledger['block']}" if ledger["enabled"] else ledger["reason"][:60])
    with c[2]:
        port = os.environ.get("INVOICEGUARD_API_PORT")
        kpi_card("REST API", f"Port {port}" if port else "Not started", "check" if port else "inbox",
                 "success" if port else "accent", "Set INVOICEGUARD_API_PORT to enable")
    with c[3]:
        kpi_card("In progress", str(m["by_status"].get("PROCESSING", 0) + m["by_status"].get("RECEIVED", 0)),
                 "clock", "accent", "Invoices currently inside the workflow")
    st.caption("Refreshes every 30 seconds.")


health()

left, right = st.columns(2, gap="large")
with left:
    st.html('<div class="ig-section-title">Workflow configuration</div>')
    b = ctx.spec.bounds
    notice("info", f"{ctx.spec.workflow} v{ctx.spec.version}", [
        f"Extraction strategies (in order): {', '.join(ctx.strategy_order)}",
        f"Max extraction attempts {b.max_iterations} · max tool calls {b.max_tool_calls} · timeout {b.timeout_seconds}s",
        f"Approver role: {ctx.spec.approver}"])
    st.caption("Whether Tesseract or the Claude strategy is actually available is only known when it runs; "
               "unavailable strategies are skipped and logged as EXTRACTION_RETRIED.")
    st.html('<div class="ig-section-title">Webhook notifications</div>')
    if ctx.notifier is None:
        st.caption("Not configured (set INVOICEGUARD_WEBHOOK_URL to send events to n8n, Slack or email).")
    else:
        notice("info", "Webhook configured", [f"Target: {ctx.notifier.url}", f"{len(ctx.notifier.sent)} events sent this session"])
with right:
    st.html('<div class="ig-section-title">Live event stream</div>')

    @st.fragment(run_every="10s")
    def stream() -> None:
        events = data.recent_events(25)
        if not events:
            st.caption("No events yet.")
            return
        st.dataframe(pd.DataFrame([{"#": e["seq"], "Time": when(e["timestamp"]), "Event": friendly(e["event_type"]),
                                    "Invoice": e["invoice_id"] or "-", "Actor": e["actor"],
                                    "Details": json.dumps(e["event_data"], default=str)[:120]} for e in events]),
                     hide_index=True, width="stretch", height=420)

    stream()
