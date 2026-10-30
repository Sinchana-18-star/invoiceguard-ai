"""InvoiceGuard AI - Streamlit entry point.

    streamlit run app/streamlit_app.py
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
for p in (ROOT, ROOT / "app"):
    if str(p) not in sys.path:
        sys.path.insert(0, str(p))

import streamlit as st  # noqa: E402

st.set_page_config(page_title="InvoiceGuard AI", page_icon="🛡️", layout="wide")

from components.common import get_ctx, render_user_picker  # noqa: E402

get_ctx()
st.sidebar.title("🛡️ InvoiceGuard AI")
st.sidebar.caption("Agentic invoice verification - human approval required")
render_user_picker()

pages = st.navigation({
    "Overview": [st.Page("pages/dashboard.py", title="Dashboard", icon="📊", default=True),
                 st.Page("pages/spec.py", title="Workflow Spec & Graph", icon="🧭")],
    "Work": [
        st.Page("pages/employee.py", title="Employee - Upload", icon="📤"),
        st.Page("pages/manager.py", title="Manager - Approvals", icon="✅"),
        st.Page("pages/invoice_review.py", title="Invoice Review", icon="🔍"),
    ],
    "Control": [
        st.Page("pages/audit.py", title="Audit Log", icon="🔗"),
        st.Page("pages/master_data.py", title="Suppliers, POs & GRNs", icon="🗂️"),
    ],
})
pages.run()
