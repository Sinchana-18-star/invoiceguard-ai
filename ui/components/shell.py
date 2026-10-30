"""Application shell: sidebar profile (demo sign-in), page header with breadcrumb, search and notifications."""
from __future__ import annotations

import streamlit as st

from core.db import Status
from ui import data
from ui.access import PAGES, allowed
from ui.components.badges import status_label
from ui.format import esc, initials, md_safe, money
from ui.runtime import ROLE_LABELS, current_user


def sidebar_profile() -> None:
    """User profile at the bottom of the sidebar. Demo build: pick a demo user (no passwords)."""
    users = data.users()
    ids = [u["id"] for u in users]
    labels = {u["id"]: f"{u['name'].split(' (')[0]} · {ROLE_LABELS.get(u['role'], u['role'])}" for u in users}
    user = current_user()

    def _picked():
        st.session_state["user_id"] = st.session_state["_user_picker"]
        for k in ("review_invoice_id", "_last_submission", "_last_decision", "_chain"):
            st.session_state.pop(k, None)

    with st.sidebar:
        limit = f"Approval limit {money(user['approval_limit'])}" if user["approval_limit"] else "No approval rights"
        st.html(f'<div class="ig-profile"><b>{esc(user["name"].split(" (")[0])}</b><br>'
                f'{esc(ROLE_LABELS.get(user["role"], user["role"]))} · {esc(limit)}</div>')
        st.selectbox("Switch demo user", ids, index=ids.index(user["id"]), format_func=labels.get,
                     key="_user_picker", on_change=_picked)
        st.caption("Demo sign-in · fictional data")


def _search(user: dict) -> None:
    with st.popover("Search", icon=":material/search:", width="stretch"):
        q = st.text_input("Invoice ID, number or supplier", key="_global_search", placeholder="e.g. DSW-2026")
        if not q:
            st.caption("Search invoices you are allowed to see.")
            return
        ql = q.strip().lower()
        hits = [i for i in data.invoices_for(user)
                if ql in " ".join(str(i.get(k) or "") for k in ("id", "invoice_number", "supplier_name",
                                                                  "file_name")).lower()][:8]
        if not hits:
            st.caption("No matching invoices.")
        for inv in hits:
            label = f"{md_safe(inv['invoice_number'] or inv['file_name'])} · {status_label(inv['status'])}"
            if st.button(label, key=f"_hit_{inv['id']}", width="stretch"):
                st.session_state["review_invoice_id"] = inv["id"]
                st.switch_page(PAGES["review"][0])


def _notifications(user: dict) -> None:
    if user["role"] == "accounts_manager":
        items = data.invoices(statuses=Status.PENDING_DECISION)
        items = [i for i in items if i["uploader_id"] != user["id"]]
        title = "Waiting for a decision"
    else:
        items = [i for i in data.invoices_for(user)
                 if i["status"] in (Status.ESCALATED, Status.BLOCKED, Status.REJECTED)][:10]
        title = "Needs attention"
    with st.popover(f"{len(items)}" if items else "0", icon=":material/notifications:", width="stretch",
                    help="Notifications"):
        st.markdown(f"**{title}**")
        if not items:
            st.caption("Nothing right now.")
        for inv in items[:10]:
            if st.button(f"{status_label(inv['status'])} · {md_safe(inv['invoice_number'] or inv['id'])}",
                         key=f"_n_{inv['id']}", width="stretch"):
                st.session_state["review_invoice_id"] = inv["id"]
                target = "manager" if allowed(user, "manager") and inv["status"] in Status.PENDING_DECISION else "review"
                st.switch_page(PAGES[target][0])


def page_header(page_key: str, section: str, subtitle: str | None = None) -> dict:
    """Renders the header and returns the signed-in user."""
    user = current_user()
    title = PAGES[page_key][1]
    left, s, n, u = st.columns([6, 1.3, 0.8, 2.2], vertical_alignment="center")
    with left:
        st.html(f'<div class="ig-breadcrumb">InvoiceGuard AI / {esc(section)} / <b>{esc(title)}</b></div>'
                f'<div class="ig-title">{esc(title)}</div>'
                + (f'<div class="ig-subtitle">{esc(subtitle)}</div>' if subtitle else ""))
    with s:
        _search(user)
    with n:
        _notifications(user)
    with u:
        st.html(f'<div style="text-align:right"><span class="ig-user-chip"><span class="ig-avatar">'
                f'{esc(initials(user["name"]))}</span><span><b>{esc(user["name"].split(" (")[0])}</b> '
                f'<span class="ig-role">· {esc(ROLE_LABELS.get(user["role"], user["role"]))}</span></span>'
                f'</span></div>')
    st.divider()
    return user
