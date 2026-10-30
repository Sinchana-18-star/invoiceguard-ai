"""Process-wide app context, CSS loading and the signed-in demo user."""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from core.context import AppContext
from core.demo_data import seed_demo_data

UI_DIR = Path(__file__).resolve().parent
ROLE_LABELS = {"employee": "Employee", "accounts_manager": "Accounts Manager", "auditor": "Auditor"}


@st.cache_resource
def get_ctx() -> AppContext:
    ctx = AppContext()
    seed_demo_data(ctx)
    port = os.environ.get("INVOICEGUARD_API_PORT")
    if port:  # REST API for n8n etc., in this process so it shares the same ledger and audit log
        from api.server import start_in_thread
        start_in_thread(ctx, int(port))
    return ctx


def _css() -> str:
    return (UI_DIR / "styles.css").read_text(encoding="utf-8")


def load_css() -> None:
    st.html(f"<style>{_css()}</style>")


def current_user() -> dict:
    from ui import data

    users = data.users()
    ids = [u["id"] for u in users]
    if st.session_state.get("user_id") not in ids:
        st.session_state["user_id"] = "emp_asha" if "emp_asha" in ids else ids[0]
    return next(u for u in users if u["id"] == st.session_state["user_id"])
