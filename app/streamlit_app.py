"""InvoiceGuard AI - Streamlit entry point.

    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="InvoiceGuard AI", page_icon=str(ROOT / "ui" / "assets" / "icon.svg"),
                   layout="wide", initial_sidebar_state="expanded")

from ui.access import navigation_for  # noqa: E402
from ui.components.shell import sidebar_profile  # noqa: E402
from ui.runtime import current_user, get_ctx, load_css  # noqa: E402

load_css()
st.logo(str(ROOT / "ui" / "assets" / "logo.svg"), size="large", icon_image=str(ROOT / "ui" / "assets" / "icon.svg"))
with st.spinner("Starting InvoiceGuard AI..."):
    get_ctx()

user = current_user()
nav = st.navigation(navigation_for(user))  # role-based: employees never get Manager Approvals
sidebar_profile()
nav.run()
