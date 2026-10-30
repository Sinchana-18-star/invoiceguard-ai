import streamlit as st

from components.common import current_user, get_ctx, inr, render_document, show_issues, status_badge
from core import service
from core.db import Status

ctx = get_ctx()
user = current_user()
st.title("Manager - Approvals")

if user.role != ctx.spec.approver:
    st.warning(f"You are signed in as **{user.role}**. Only `{ctx.spec.approver}` users can make decisions. "
               "Switch user in the sidebar to try.")

queue = service.list_invoices(ctx, statuses=Status.PENDING_DECISION)
if not queue:
    st.info("Nothing is waiting for a decision.")
    st.stop()

labels = {i["id"]: f"{i['status']} · {i['id']} · {i['supplier_name'] or i['file_name']} · ₹{inr(i['grand_total'])}"
          for i in queue}
selected = st.selectbox("Waiting for a decision", list(labels), format_func=labels.get)
inv = service.get_invoice(ctx, selected)
pending = inv["pending"] or {}

st.markdown(f"{status_badge(inv['status'])}  **{inv['invoice_number'] or '-'}** from **{inv['supplier_name'] or '-'}** · "
            f"PO `{inv['po_number'] or '-'}` · uploaded by `{inv['uploader_id']}`")
risk = (inv["checker"] or {}).get("risk") or {}
ledger = inv.get("ledger") or {}
k = st.columns(5)
k[0].metric("Grand total", f"₹{inr(inv['grand_total'])}")
k[1].metric("Confidence", f"{(inv['confidence'] or 0):.2f}")
k[2].metric("Checker", "PASSED" if (inv["checker"] or {}).get("passed") else "FAILED")
k[3].metric("Fraud risk", f"{risk.get('score', '-')}/100", risk.get("level"), delta_color="off")
k[4].metric("Your limit", f"₹{inr(user.approval_limit)}" if user.approval_limit else "-")
if inv["flags"]:
    st.warning("Flags: " + ", ".join(inv["flags"]))
if risk.get("signals"):
    box = st.error if risk["level"] == "HIGH" else st.warning if risk["level"] == "MEDIUM" else st.info
    box("**Why this risk score:**\n" + "\n".join(f"- +{s['points']} {s['code']}: {s['detail']}"
                                                  for s in risk["signals"]))
if ledger.get("status") == "REGISTERED_ELSEWHERE":
    st.error(f"⛓️ Blockchain: this invoice was already registered by another organisation ({ledger.get('registrar')}). "
             "Possible double financing / double payment.")
elif ledger.get("tx_hash") or ledger.get("status") == "ALREADY_OURS":
    st.caption(f"⛓️ Fingerprint on chain {ledger.get('chain_id')} · contract `{ledger.get('contract', '')[:12]}…` · "
               f"tx `{(ledger.get('tx_hash') or '')[:18]}…`")

left, right = st.columns([1, 1])
with left:
    render_document(inv["file_path"], key=f"mgr_{selected}")
with right:
    show_issues(inv)
    with st.expander("Checker evidence", expanded=True):
        for e in (inv["checker"] or {}).get("evidence", []):
            st.markdown(f"- {e}")
        calc = (inv["checker"] or {}).get("calculated_values")
        if calc:
            st.caption("Independently calculated: " + ", ".join(f"{a} ₹{inr(b)}" for a, b in calc.items()))
    if inv["approvals"]:
        with st.expander("Decision history"):
            for a in inv["approvals"]:
                st.markdown(f"- `{a['manager_id']}` **{a['decision']}** - {a['reason'] or ''}")

st.divider()
reason = st.text_input("Reason (required for reject / escalate / release)", key=f"reason_{selected}")
allowed = pending.get("allowed_actions", [])


def act(action):
    try:
        out = service.decide(ctx, selected, user.id, action, reason=reason or None)
        st.toast(f"{selected}: {out['status']}")
        st.rerun()
    except (PermissionError, ValueError, service.WorkflowError) as e:
        st.error(str(e))


cols = st.columns(4)
if "approve" in allowed and cols[0].button("✅ Approve", type="primary", width="stretch"):
    act("approve")
if "reject" in allowed and cols[1].button("❌ Reject", width="stretch"):
    act("reject")
if "escalate" in allowed and cols[2].button("⬆️ Escalate", width="stretch"):
    act("escalate")
if "release" in allowed and (inv["checker"] or {}).get("passed") and cols[3].button("🔓 Release to approval",
                                                                                     width="stretch"):
    act("release")
if "correct" in allowed:
    st.caption("To fix extracted fields, open the invoice in **Invoice Review** - the workflow re-runs validation "
               "and the checker after every correction.")
    if st.button("Open in Invoice Review"):
        st.session_state["review_invoice_id"] = selected
        st.switch_page("pages/invoice_review.py")
