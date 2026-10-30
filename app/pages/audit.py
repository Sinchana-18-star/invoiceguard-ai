import pandas as pd
import streamlit as st

from components.common import get_ctx, inr
from core import service

ctx = get_ctx()
st.title("Audit Log")
st.caption("Every step is appended to `audit.jsonl`. Each entry stores the SHA-256 hash of the previous entry, "
           "so editing or deleting any line breaks the chain.")

if st.button("🔗 Verify hash chain", type="primary"):
    report = ctx.audit.verify_chain()
    if report["intact"]:
        st.success(f"Audit log intact - {report['count']} events verified. Head hash `{report['head_hash'][:16]}…`")
    else:
        st.error(f"TAMPERING DETECTED at event #{report['first_broken_seq']}: {report['reason']}")

st.subheader("⛓️ Shared blockchain ledger")
info = service.ledger_info(ctx)
if not info["enabled"]:
    st.warning(f"Ledger disabled: {info['reason']}")
else:
    st.caption(f"Mode `{info['mode']}` · chain id {info['chain_id']} · contract `{info['contract']}` · "
               f"our account `{info['account']}` · {info['total_registered']} fingerprints · block {info['block']}")
    st.caption("Only SHA-256(salt | supplier GSTIN | invoice number) is stored on chain - never invoice data.")
    if info["mode"] == "local":
        with st.expander("Demo: another organisation registers an invoice first (double financing)"):
            st.caption("Simulates a second buyer or lender on the same chain registering an invoice. Upload the "
                       "same invoice afterwards and InvoiceGuard escalates it as possible double financing.")
            c1, c2 = st.columns(2)
            gstin = c1.text_input("Supplier GSTIN", value="29AAACS5678K1ZP")
            number = c2.text_input("Invoice number", value="DSW/26-27/0108")  # samples/10_table_layout_valid.pdf
            if st.button("Register as the other organisation"):
                try:
                    r = service.simulate_other_organisation_registration(ctx, gstin, number)
                    st.success(f"{r['status']} by {r['organisation']}" + (f" · tx {r['tx_hash'][:18]}…"
                                                                          if r.get("tx_hash") else ""))
                except Exception as e:
                    st.error(str(e))

st.subheader("Invoices")
rows = [{"Invoice ID": i["id"], "Employee": i["uploader_id"], "Supplier": i["supplier_name"],
         "Total (₹)": inr(i["grand_total"]), "Status": i["status"],
         "Verification": {True: "PASSED", False: "FAILED"}.get((i["checker"] or {}).get("passed"), "-"),
         "Risk": ((i["checker"] or {}).get("risk") or {}).get("score", "-"),
         "Ledger": (i.get("ledger") or {}).get("status", "-"),
         "Decision": f"{i['decided_by'] or ''} {i['decision_reason'] or ''}".strip() or "-",
         "Updated (UTC)": str(i["updated_at"])[:19]} for i in service.list_invoices(ctx)]
if rows:
    st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch")

st.subheader("Events")
ids = ["(all)"] + [r["Invoice ID"] for r in rows]
pick = st.selectbox("Invoice", ids)
events = ctx.audit.get_recent_events(500) if pick == "(all)" else ctx.audit.get_invoice_history(pick)
if events:
    st.dataframe(pd.DataFrame([{"#": e["seq"], "timestamp": e["timestamp"], "invoice": e["invoice_id"],
                                "event": e["event_type"], "actor": e["actor"],
                                "data": str(e["event_data"])[:200]} for e in events]),
                 hide_index=True, width="stretch")
