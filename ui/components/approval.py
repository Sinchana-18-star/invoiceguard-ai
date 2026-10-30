"""Approval actions with st.dialog confirmations. Every action calls the real workflow (service.decide);
the UI only explains in advance why an action is unavailable, using the backend's own rules."""
from __future__ import annotations

import streamlit as st

from ui import data
from ui.format import esc, money

THREE_WAY_CODES = ("PO_NOT_FOUND", "SUPPLIER_MISMATCH", "GRN_NOT_FOUND", "ITEM_NOT_ON_PO", "OVER_RECEIPT",
                   "QTY_EXCEEDS_RECEIPT", "PRICE_MISMATCH")
THREE_WAY_EVIDENCE = ("PO ", "GRN", "Line ", "Invoice supplier matches")


def split_three_way(checker: dict) -> tuple[list[str], list[str], list[str], list[str]]:
    """(3-way reasons, 3-way evidence, other reasons, other evidence) - a view over the checker's output."""
    reasons, evidence = checker.get("reasons", []), checker.get("evidence", [])
    tw_r = [r for r in reasons if r.startswith(THREE_WAY_CODES)]
    tw_e = [e for e in evidence if e.startswith(THREE_WAY_EVIDENCE)]
    return tw_r, tw_e, [r for r in reasons if r not in tw_r], [e for e in evidence if e not in tw_e]


def approve_blockers(inv: dict, user: dict) -> list[str]:
    """Plain-language reasons the Approve button is disabled. The backend re-checks on submit regardless."""
    reasons = []
    if not (inv.get("checker") or {}).get("passed"):
        reasons.append("The independent checker has not passed for this invoice.")
    if inv["uploader_id"] == user["id"]:
        reasons.append("You uploaded this invoice (separation of duties).")
    if user["approval_limit"] is None or (inv["grand_total"] is not None and inv["grand_total"] > user["approval_limit"]):
        reasons.append(f"The amount {money(inv['grand_total'])} exceeds your approval limit "
                       f"{money(user['approval_limit'])}.")
    for err in data.approval_blockers(inv["id"], user["id"]):
        code = err.split(":")[0]
        if code == "MAKER_CHECKER":
            reasons.append("You corrected or released this invoice, so another manager must approve it.")
        elif code not in ("SEPARATION_OF_DUTIES", "APPROVAL_LIMIT_EXCEEDED", "NOT_ELIGIBLE"):
            reasons.append(err)
    return reasons


def _run(invoice_id: str, user: dict, action: str, reason: str | None = None) -> None:
    try:
        out = data.decide(invoice_id, user["id"], action, reason=reason)
        st.session_state["_last_decision"] = ("success", f"{action.title()} recorded for {invoice_id}. "
                                                         f"Backend status is now {out['status']}.")
    except (PermissionError, ValueError) as e:
        st.session_state["_last_decision"] = ("danger", f"The backend refused '{action}': {e}")
    except Exception as e:  # noqa: BLE001 - WorkflowError and anything unexpected
        st.session_state["_last_decision"] = ("danger", f"{e.__class__.__name__}: {e}")
    # The queue changes after a decision; drop the old row selection so it can't point at another invoice.
    st.session_state["_queue_v"] = st.session_state.get("_queue_v", 0) + 1
    st.session_state.pop("review_invoice_id", None)
    st.rerun()


@st.dialog("Approve invoice")
def approve_dialog(inv: dict, user: dict) -> None:
    st.html(f"Approve <b>{esc(inv['invoice_number'])}</b> from {esc(inv['supplier_name'])} for "
            f"<b class='ig-num'>{esc(money(inv['grand_total']))}</b>?")
    st.caption("This records your decision in the audit log and on the ledger. No payment is made by InvoiceGuard.")
    c1, c2 = st.columns(2)
    if c1.button("Confirm approval", type="primary", width="stretch"):
        _run(inv["id"], user, "approve")
    if c2.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Reject invoice")
def reject_dialog(inv: dict, user: dict) -> None:
    st.html(f"Reject <b>{esc(inv['invoice_number'] or inv['id'])}</b>?")
    reason = st.text_area("Reason (required, stored in the audit log)", key=f"rej_{inv['id']}")
    c1, c2 = st.columns(2)
    if c1.button("Confirm rejection", type="primary", width="stretch"):
        if reason.strip():
            _run(inv["id"], user, "reject", reason.strip())
        st.error("A reason is required to reject. Nothing was sent.")
    if c2.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Escalate invoice")
def escalate_dialog(inv: dict, user: dict) -> None:
    reason = st.text_area("Why does this need further review? (required)", key=f"esc_{inv['id']}")
    c1, c2 = st.columns(2)
    if c1.button("Confirm escalation", type="primary", width="stretch"):
        if reason.strip():
            _run(inv["id"], user, "escalate", reason.strip())
        st.error("A reason is required. Nothing was sent.")
    if c2.button("Cancel", width="stretch"):
        st.rerun()


@st.dialog("Release to approval")
def release_dialog(inv: dict, user: dict) -> None:
    st.write("Release this escalated invoice to the approval queue. It passed the independent checker; a "
             "different manager will have to approve it.")
    reason = st.text_area("What did you verify? (required)", key=f"rel_{inv['id']}")
    c1, c2 = st.columns(2)
    if c1.button("Confirm release", type="primary", width="stretch"):
        if reason.strip():
            _run(inv["id"], user, "release", reason.strip())
        st.error("A reason is required. Nothing was sent.")
    if c2.button("Cancel", width="stretch"):
        st.rerun()
