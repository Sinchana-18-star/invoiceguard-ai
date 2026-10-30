"""Role-based page visibility. Hiding a page is UX only - every decision is still enforced by the backend
(core/authz.py) when the workflow resumes."""
from __future__ import annotations

import streamlit as st

PAGES = {
    "dashboard": ("pages/dashboard.py", "Dashboard", ":material/space_dashboard:"),
    "employee": ("pages/employee.py", "Employee Workspace", ":material/upload_file:"),
    "review": ("pages/invoice_review.py", "Invoice Review", ":material/fact_check:"),
    "manager": ("pages/manager.py", "Manager Approvals", ":material/approval:"),
    "workflow": ("pages/workflow.py", "Workflow Pipeline", ":material/account_tree:"),
    "audit": ("pages/audit.py", "Audit & Compliance", ":material/verified_user:"),
    "monitoring": ("pages/monitoring.py", "System Monitoring", ":material/monitor_heart:"),
    "settings": ("pages/settings.py", "Settings", ":material/settings:"),
}
SECTIONS = {
    "Overview": ["dashboard", "workflow"],
    "Operations": ["employee", "review", "manager"],
    "Governance": ["audit", "monitoring", "settings"],
}
ROLE_PAGES = {
    "employee": {"dashboard", "employee", "review", "workflow"},
    "accounts_manager": set(PAGES),
    "auditor": {"dashboard", "review", "workflow", "audit", "monitoring", "settings"},
}


def allowed(user: dict, page: str) -> bool:
    return page in ROLE_PAGES.get(user["role"], set())


def navigation_for(user: dict) -> dict:
    nav = {}
    for section, keys in SECTIONS.items():
        pages = [st.Page(PAGES[k][0], title=PAGES[k][1], icon=PAGES[k][2], default=(k == "dashboard"))
                 for k in keys if allowed(user, k)]
        if pages:
            nav[section] = pages
    return nav


def require(user: dict, page: str) -> None:
    """No-permission state for pages reached by a stale link after switching user."""
    if not allowed(user, page):
        from ui.components.states import no_permission
        no_permission(PAGES[page][1], user)
        st.stop()


def sees_all_invoices(user: dict) -> bool:
    return user["role"] in ("accounts_manager", "auditor")
