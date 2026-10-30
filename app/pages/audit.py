import json

import pandas as pd
import streamlit as st

from ui import data
from ui.access import require
from ui.components.audit_timeline import friendly, timeline
from ui.components.shell import page_header
from ui.components.states import empty_state, notice
from ui.format import md_safe, money, when

user = page_header("audit", "Governance", "Append-only, SHA-256 hash-chained audit log. Integrity is verified by "
                                          "the backend on every check.")
require(user, "audit")

# ---------------------------------------------------------------- integrity
st.html('<div class="ig-section-title">Audit integrity</div>')
with st.container(border=True):
    c1, c2 = st.columns([3, 1], vertical_alignment="center")
    c1.caption("Recomputes every hash in audit.jsonl with the backend's verify_chain(). Editing, inserting or "
               "deleting any line breaks the chain from that point.")
    if c2.button("Verify chain now", type="primary", icon=":material/verified:", width="stretch"):
        st.session_state["_chain"] = data.verify_chain()
    chain = st.session_state.get("_chain")
    if chain is None:
        st.caption("Not verified in this session yet.")
    elif chain["intact"]:
        notice("success", "Chain verified", body=f"{chain['count']} events verified. Head hash {chain['head_hash']}")
    else:
        notice("danger", f"Integrity failure at entry {chain['first_broken_seq']}",
               body=f"{chain['reason']}. Events from entry {chain['first_broken_seq']} onwards cannot be trusted.")

# ---------------------------------------------------------------- invoices
st.html('<div class="ig-section-title">Invoices</div>')
invoices = data.invoices()
if not invoices:
    empty_state("No invoices yet")
else:
    st.dataframe(pd.DataFrame([{
        "Invoice ID": i["id"], "Employee": i["uploader_id"], "Supplier": i["supplier_name"] or "-",
        "Amount": money(i["grand_total"]), "Status": i["status"],
        "Checker": {True: "Passed", False: "Failed"}.get((i["checker"] or {}).get("passed"), "-"),
        "Risk": str(((i["checker"] or {}).get("risk") or {}).get("score", "-")),
        "Ledger": (i.get("ledger") or {}).get("status", "-"),
        "Decision": f"{i['decided_by'] or ''} {i['decision_reason'] or ''}".strip() or "-",
        "Updated": when(i["updated_at"])} for i in invoices]), hide_index=True, width="stretch")

# ---------------------------------------------------------------- events
st.html('<div class="ig-section-title">Event log</div>')
ids = [i["id"] for i in invoices]
pick = st.selectbox("Invoice", ["(all invoices - latest 300)"] + ids)
chain = st.session_state.get("_chain")
if pick.startswith("("):
    events = data.recent_events(300)
    st.caption("The all-invoices view comes from the audit_events table, which does not expose hashes to the UI. "
               "Pick a single invoice to see previous/current hashes from the hash-chained log.")
    st.dataframe(pd.DataFrame([{"#": e["seq"], "Invoice ID": e["invoice_id"], "Event": friendly(e["event_type"]),
                                "Actor": e["actor"], "Timestamp": when(e["timestamp"]),
                                "Details": json.dumps(e["event_data"], default=str)[:200]} for e in events]),
                 hide_index=True, width="stretch")
else:
    events = data.history(pick)
    view = st.segmented_control("View", ["Timeline", "Table"], default="Timeline", label_visibility="collapsed")
    if view == "Table":
        broken = chain["first_broken_seq"] if chain and not chain["intact"] else None
        st.dataframe(pd.DataFrame([{
            "#": e["seq"], "Event": friendly(e["event_type"]), "Actor": e["actor"], "Timestamp": when(e["timestamp"]),
            "Previous hash": e["previous_hash"], "Current hash": e["current_hash"],
            "Integrity": ("Not verified" if chain is None else "Unverified" if broken and e["seq"] >= broken else "Verified"),
            "Details": json.dumps(e["event_data"], default=str)} for e in events]), hide_index=True, width="stretch")
    else:
        timeline(events, chain, show_hashes=True)
    if chain is None:
        st.caption("Run 'Verify chain now' to mark events as verified.")

# ---------------------------------------------------------------- blockchain ledger
st.html('<div class="ig-section-title">Shared blockchain ledger</div>')
info = data.ledger_info()
if not info["enabled"]:
    notice("warning", "Ledger disabled", body=info["reason"])
else:
    notice("info", f"Connected ({info['mode']})",
           [f"Chain id {info['chain_id']} · block {info['block']}", f"Contract {info['contract']}",
            f"Our account {info['account']}", f"{info['total_registered']} invoice fingerprints registered",
            "Only SHA-256(salt | GSTIN | invoice number) is stored on chain - never invoice data."])
    if info["mode"] == "local" and user["role"] == "accounts_manager":
        with st.expander("Demo: another organisation registers an invoice first (double financing)"):
            st.caption("Simulates a second buyer or lender on the same local chain. Upload the same invoice "
                       "afterwards and it is escalated as possible double financing.")
            c1, c2 = st.columns(2)
            gstin = c1.text_input("Supplier GSTIN", value="29AAACS5678K1ZP")
            number = c2.text_input("Invoice number", value="DSW/26-27/0108")
            if st.button("Register as the other organisation"):
                from core import service
                from ui.runtime import get_ctx
                try:
                    r = service.simulate_other_organisation_registration(get_ctx(), gstin, number)
                    data.invalidate()
                    st.success(f"{r['status']} by {r['organisation']}" + (f" · tx {r['tx_hash']}" if r.get("tx_hash") else ""))
                except Exception as e:  # noqa: BLE001
                    st.error(md_safe(e))
