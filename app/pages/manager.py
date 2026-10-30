import pandas as pd
import streamlit as st

from core.db import Status
from ui import data
from ui.access import PAGES, require
from ui.components import approval
from ui.components.audit_timeline import timeline
from ui.components.badges import risk_badge, risk_of, status_badge, status_label, verification, verification_badge
from ui.components.fields import SECTIONS, field_table
from ui.components.kpi import kpi_card
from ui.components.preview import document_preview
from ui.components.shell import page_header
from ui.components.states import empty_state, error_state, notice
from ui.format import esc, money
from ui.runtime import get_ctx

user = page_header("manager", "Operations", "Every decision is enforced by the workflow, not by this screen.")
require(user, "manager")
spec = get_ctx().spec

if "_last_decision" in st.session_state:
    kind, msg = st.session_state.pop("_last_decision")
    notice(kind, "Decision result" if kind == "success" else "Decision not applied", body=msg)

queue = data.invoices(statuses=Status.PENDING_DECISION)
awaiting = [i for i in queue if i["status"] == Status.AWAITING_APPROVAL]
within = [i for i in awaiting if user["approval_limit"] and i["grand_total"] is not None
          and i["grand_total"] <= user["approval_limit"] and i["uploader_id"] != user["id"]]
k = st.columns(4)
with k[0]:
    kpi_card("Pending approval", str(len(awaiting)), "clock", "warning")
with k[1]:
    kpi_card("Escalated for review", str(len(queue) - len(awaiting)), "alert", "danger")
with k[2]:
    kpi_card("You can approve", str(len(within)), "check", "success", "Within your limit, not uploaded by you")
with k[3]:
    kpi_card("Your approval limit", money(user["approval_limit"]), "percent", "accent")

if not queue:
    empty_state("The approval queue is empty", "New invoices appear here once they pass verification.",
                icon=":material/task_alt:")
    st.stop()

st.html('<div class="ig-section-title">Approval queue</div>')
rows = [{"Invoice": i["invoice_number"] or i["file_name"], "Supplier": i["supplier_name"] or "-",
         "Amount": money(i["grand_total"]), "Uploaded by": i["uploader_id"] + (" (you)" if i["uploader_id"] == user["id"] else ""),
         "Status": status_label(i["status"]), "Verification": verification(i)[0],
         "Risk": (f"{risk_of(i)['score']} {risk_of(i)['level'].title()}" if risk_of(i) else "-"),
         "ID": i["id"]} for i in queue]
event = st.dataframe(pd.DataFrame(rows), hide_index=True, width="stretch", on_select="rerun",
                     selection_mode="single-row", key=f"queue_{st.session_state.get('_queue_v', 0)}",
                     column_config={"ID": st.column_config.TextColumn(width="small")})
picked = event.selection.rows if event and event.selection else []
default_id = st.session_state.get("review_invoice_id")
idx = picked[0] if picked else next((n for n, i in enumerate(queue) if i["id"] == default_id), 0)
if not picked:
    st.caption("Select a row to review it. Showing the first item.")

try:
    inv = data.invoice(queue[idx]["id"])
except Exception as e:  # noqa: BLE001
    error_state("load the invoice", e)
    st.stop()
pending = inv["pending"] or {}
allowed_actions = pending.get("allowed_actions", [])
st.session_state["review_invoice_id"] = inv["id"]

# ---------------------------------------------------------------- detail panel
st.html('<div class="ig-section-title">Review panel</div>')
with st.container(border=True):
    st.html(f"<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'>"
            f"<span class='ig-title' style='font-size:18px'>{esc(inv['invoice_number'] or inv['id'])}</span>"
            f"{status_badge(inv['status'])}{verification_badge(inv)}{risk_badge(inv)}</div>"
            f"<div class='ig-subtitle'>{esc(inv['supplier_name'] or '-')} · PO {esc(inv['po_number'] or '-')} · "
            f"<span class='ig-num'>{esc(money(inv['grand_total']))}</span> · uploaded by {esc(inv['uploader_id'])}</div>")
    if inv["flags"]:
        notice("warning", "Flags raised by the workflow", inv["flags"])

    # actions first, so the reason an action is unavailable is visible immediately
    a1, a2, a3, a4 = st.columns(4)
    if pending.get("type") == "approval":
        blockers = approval.approve_blockers(inv, user)
        if a1.button("Approve", type="primary", width="stretch", disabled=bool(blockers), icon=":material/check:"):
            approval.approve_dialog(inv, user)
        if a2.button("Reject", width="stretch", icon=":material/close:"):
            approval.reject_dialog(inv, user)
        if "escalate" in allowed_actions and a3.button("Escalate", width="stretch", icon=":material/flag:"):
            approval.escalate_dialog(inv, user)
        if blockers:
            notice("info", "Approve is unavailable", blockers)
    elif pending.get("type") == "manual_review":
        passed = (inv.get("checker") or {}).get("passed")
        if a1.button("Release to approval", type="primary", width="stretch", disabled=not passed,
                     icon=":material/lock_open:"):
            approval.release_dialog(inv, user)
        if a2.button("Reject", width="stretch", icon=":material/close:"):
            approval.reject_dialog(inv, user)
        notice("warning", "Escalated: manual review",
               [inv["escalation_reason"] or "Escalated"] +
               ([] if passed else ["Release is unavailable because the independent checker has not passed. "
                                   "Correct the fields in Invoice Review or reject."]))
    if "correct" in allowed_actions and a4.button("Correct fields", width="stretch", icon=":material/edit:"):
        st.switch_page(PAGES["review"][0])

    tabs = st.tabs(["Summary", "Extracted values", "Validation", "Checker & 3-way match", "Risk & ledger",
                    "Document", "Audit history"])
    checker = inv.get("checker") or {}
    tw_r, tw_e, other_r, other_e = approval.split_three_way(checker)
    with tabs[0]:
        s1, s2, s3 = st.columns(3)
        s1.metric("Grand total", money(inv["grand_total"]))
        s2.metric("Extraction confidence", f"{(inv['confidence'] or 0):.2f}")
        s3.metric("Checker", "Passed" if checker.get("passed") else "Failed" if checker else "Not run")
        if inv["approvals"]:
            st.caption("Previous decisions")
            st.dataframe(pd.DataFrame([{"Manager": a["manager_id"], "Decision": a["decision"],
                                        "Reason": a["reason"] or "-", "At": str(a["at"])[:19]}
                                       for a in inv["approvals"]]), hide_index=True, width="stretch")
    with tabs[1]:
        f, c = inv["extracted"] or {}, inv["field_confidence"] or {}
        for title, keys in SECTIONS.items():
            st.html(f'<div class="ig-section-title">{esc(title)}</div>')
            field_table(f, c, keys, spec)
        if f.get("line_items"):
            st.dataframe(pd.DataFrame([{"Description": li.get("description"), "Qty": li.get("quantity"),
                                        "Unit price": money(li.get("unit_price")), "GST %": li.get("gst_rate"),
                                        "Taxable value": money(li.get("taxable_value"))}
                                       for li in f["line_items"]]), hide_index=True, width="stretch")
    with tabs[2]:
        v = inv.get("validation") or {}
        notice("success" if v.get("passed") else "danger", "Validation " + ("passed" if v.get("passed") else "failed"),
               [f"{e['code']}: {e['message']}" for e in v.get("errors", [])] or None)
        if v.get("warnings"):
            notice("warning", "Warnings", [f"{w['code']}: {w['message']}" for w in v["warnings"]])
    with tabs[3]:
        if not checker:
            st.caption("The independent checker has not run for this invoice.")
        else:
            notice("success" if not other_r else "danger", "GST and arithmetic", other_r or other_e)
            notice("success" if not tw_r else "danger", "Three-way match (invoice / PO / GRN)", tw_r or tw_e)
            if checker.get("warnings"):
                notice("warning", "Checker warnings", checker["warnings"])
    with tabs[4]:
        risk = risk_of(inv)
        if risk:
            notice({"HIGH": "danger", "MEDIUM": "warning", "LOW": "success"}[risk["level"]],
                   f"Fraud risk {risk['score']}/100 ({risk['level'].title()})",
                   [f"+{s['points']} {s['code']}: {s['detail']}" for s in risk["signals"]] or ["No risk signals"])
        ledger = inv.get("ledger") or {}
        if ledger.get("status") == "REGISTERED_ELSEWHERE":
            notice("danger", "Blockchain: registered by another organisation",
                   body=f"Registrar {ledger.get('registrar')}. Possible double financing or double payment.")
        elif ledger:
            notice("info", f"Blockchain ledger: {ledger.get('status')}",
                   [f"{k}: {ledger[k]}" for k in ("chain_id", "contract", "tx_hash", "decision_tx") if ledger.get(k)])
    with tabs[5]:
        document_preview(inv, key=f"mgr_{inv['id']}")
    with tabs[6]:
        timeline(data.history(inv["id"]))
