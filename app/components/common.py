"""Shared Streamlit helpers: cached app context, demo login, badges, document viewer."""
from __future__ import annotations

import os
from decimal import Decimal
from pathlib import Path

import streamlit as st

from core import service
from core.context import AppContext
from core.db import Status
from core.demo_data import seed_demo_data

STATUS_COLORS = {
    Status.RECEIVED: "gray", Status.PROCESSING: "blue", Status.BLOCKED: "red", Status.AWAITING_APPROVAL: "orange",
    Status.ESCALATED: "violet", Status.APPROVED: "green", Status.REJECTED: "red",
}


@st.cache_resource
def get_ctx() -> AppContext:
    ctx = AppContext()
    seed_demo_data(ctx)
    port = os.environ.get("INVOICEGUARD_API_PORT")
    if port:  # REST API for n8n etc., in this process so it shares the same ledger and audit log
        from api.server import start_in_thread
        start_in_thread(ctx, int(port))
    return ctx


def render_user_picker() -> None:
    """Demo sign-in in the sidebar (no passwords in this hackathon build). Rendered once by streamlit_app.py."""
    users = service.list_users(get_ctx())
    labels = {u.id: f"{u.name} [{u.role}]" for u in users}
    ids = list(labels)
    # The signed-in user lives in a plain session key; Streamlit can reset widget-owned keys on page switches.
    if st.session_state.get("user_id") not in ids:
        st.session_state["user_id"] = "emp_asha" if "emp_asha" in ids else ids[0]

    def _picked():
        st.session_state["user_id"] = st.session_state["_user_picker"]

    st.sidebar.selectbox("Signed in as (demo)", ids, index=ids.index(st.session_state["user_id"]),
                         format_func=labels.get, key="_user_picker", on_change=_picked)
    user = current_user()
    if user.approval_limit is not None:
        st.sidebar.caption(f"Approval limit: ₹{inr(user.approval_limit)}")


def current_user():
    uid = st.session_state.get("user_id", "emp_asha")
    return next(u for u in service.list_users(get_ctx()) if u.id == uid)


def inr(value) -> str:
    if value in (None, ""):
        return "-"
    v = Decimal(str(value)).quantize(Decimal("0.01"))
    whole, frac = f"{v:.2f}".split(".")
    neg = whole.startswith("-")
    whole = whole.lstrip("-")
    if len(whole) > 3:  # Indian digit grouping: 12,34,567.00
        head, tail = whole[:-3], whole[-3:]
        groups = []
        while len(head) > 2:
            groups.insert(0, head[-2:])
            head = head[:-2]
        if head:
            groups.insert(0, head)
        whole = ",".join(groups + [tail])
    return f"{'-' if neg else ''}{whole}.{frac}"


def status_badge(status: str) -> str:
    return f":{STATUS_COLORS.get(status, 'gray')}-badge[{status.replace('_', ' ')}]"


def confidence_badge(conf: float | None, spec) -> str:
    if conf is None:
        return ":gray-badge[n/a]"
    t = spec.thresholds
    color = "green" if conf >= t.green_confidence else "orange" if conf >= t.amber_confidence else "red"
    return f":{color}-badge[{conf:.2f}]"


def render_document(path: str, key: str, highlights: list[str] | None = None) -> None:
    """Show a PDF page (with page navigation and optional text highlights) or an image."""
    p = Path(path)
    if not p.exists():
        st.warning("Original file not found")
        return
    if p.suffix.lower() != ".pdf":
        st.image(str(p), width="stretch")
        return
    import pymupdf

    with pymupdf.open(p) as doc:
        n = len(doc)
        page_no = st.number_input("Page", 1, n, 1, key=f"{key}_page") if n > 1 else 1
        page = doc[page_no - 1]
        for text in highlights or []:
            for rect in page.search_for(str(text)):
                annot = page.add_highlight_annot(rect)
                annot.set_colors(stroke=(1, 0.85, 0))
                annot.update()
        png = page.get_pixmap(dpi=110).tobytes("png")
    st.image(png, width="stretch")


def show_issues(inv: dict) -> None:
    v = inv.get("validation") or {}
    c = inv.get("checker") or {}
    for e in v.get("errors", []):
        st.error(f"**{e['code']}** - {e['message']}")
    for w in v.get("warnings", []):
        st.warning(f"**{w['code']}** - {w['message']}")
    for r in c.get("reasons", []):
        st.error(f"Checker: {r}")
    for w in c.get("warnings", []):
        st.warning(f"Checker: {w}")
    if inv.get("escalation_reason") and inv["status"] == Status.ESCALATED:
        st.info(f"Escalated: {inv['escalation_reason']}")
    if inv.get("failure_reason"):
        st.error(f"Blocked: {inv['failure_reason']}")
