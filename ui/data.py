"""Read-only data access for the UI (cached), plus the write calls that invalidate the cache.

Every function here calls an existing backend function; nothing is computed or stored by the UI itself.
"""
from __future__ import annotations

import streamlit as st

from core import service
from ui.runtime import get_ctx

TTL = 15


def invalidate() -> None:
    st.cache_data.clear()


@st.cache_data(ttl=TTL, show_spinner=False)
def users() -> list[dict]:
    return [{"id": u.id, "name": u.name, "role": u.role, "approval_limit": u.approval_limit}
            for u in service.list_users(get_ctx())]


@st.cache_data(ttl=TTL, show_spinner=False)
def invoices(statuses: tuple[str, ...] | None = None, uploader_id: str | None = None) -> list[dict]:
    return service.list_invoices(get_ctx(), statuses=statuses, uploader_id=uploader_id)


def invoices_for(user: dict, statuses: tuple[str, ...] | None = None) -> list[dict]:
    from ui.access import sees_all_invoices
    return invoices(statuses, None if sees_all_invoices(user) else user["id"])


@st.cache_data(ttl=TTL, show_spinner=False)
def invoice(invoice_id: str) -> dict:
    return service.get_invoice(get_ctx(), invoice_id)


@st.cache_data(ttl=TTL, show_spinner=False)
def workflow_state(invoice_id: str) -> dict:
    return service.workflow_state(get_ctx(), invoice_id)


@st.cache_data(ttl=TTL, show_spinner=False)
def metrics() -> dict:
    return service.metrics(get_ctx())


@st.cache_data(ttl=TTL, show_spinner=False)
def history(invoice_id: str) -> list[dict]:
    return get_ctx().audit.get_invoice_history(invoice_id)


@st.cache_data(ttl=TTL, show_spinner=False)
def recent_events(limit: int = 50) -> list[dict]:
    return get_ctx().audit.get_recent_events(limit)


@st.cache_data(ttl=TTL, show_spinner=False)
def ledger_info() -> dict:
    return service.ledger_info(get_ctx())


def verify_chain() -> dict:
    """Never cached: integrity must be recomputed by the backend every time it is shown."""
    return get_ctx().audit.verify_chain()


def approval_blockers(invoice_id: str, actor_id: str) -> list[str]:
    """Ask the backend's own authorisation rules why `actor_id` may not approve (read-only)."""
    from core.authz import decision_errors
    from core.db import Invoice

    ctx = get_ctx()
    corrected_by = workflow_state(invoice_id).get("corrected_by")
    with ctx.Session() as s:
        return decision_errors(s, ctx.spec, s.get(Invoice, invoice_id), actor_id, "approve", corrected_by)


# ---------------------------------------------------------------- writes (always followed by invalidate)
def submit(user_id: str, file_name: str, payload: bytes) -> dict:
    try:
        return service.submit_invoice(get_ctx(), user_id, file_name, payload)
    finally:
        invalidate()


def decide(invoice_id: str, actor_id: str, action: str, reason: str | None = None,
           corrections: dict | None = None) -> dict:
    try:
        return service.decide(get_ctx(), invoice_id, actor_id, action, reason=reason, corrections=corrections)
    finally:
        invalidate()
