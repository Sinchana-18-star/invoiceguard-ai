"""Empty, error, no-permission and notice blocks shared by every page."""
from __future__ import annotations

import streamlit as st

from ui.format import esc


def notice(kind: str, title: str, items: list[str] | None = None, body: str | None = None) -> None:
    """kind: danger | warning | success | info. All text is escaped."""
    parts = [f'<div class="ig-notice ig-n-{kind}"><div class="ig-notice-title">{esc(title)}</div>']
    if body:
        parts.append(f"<div>{esc(body)}</div>")
    if items:
        parts.append('<ul class="ig-list">' + "".join(f"<li>{esc(i)}</li>" for i in items) + "</ul>")
    parts.append("</div>")
    st.html("".join(parts))


def empty_state(title: str, hint: str | None = None, icon: str = ":material/inbox:") -> None:
    with st.container(border=True):
        st.markdown(f"#### {icon} {title}")
        if hint:
            st.caption(hint)


def error_state(what: str, exc: Exception) -> None:
    notice("danger", f"Could not {what}", body=f"{exc.__class__.__name__}: {exc}")


def no_permission(page_title: str, user: dict) -> None:
    from ui.runtime import ROLE_LABELS
    with st.container(border=True):
        st.markdown(f"#### :material/lock: You don't have access to {page_title}")
        st.caption(f"Signed in as {user['name']} ({ROLE_LABELS.get(user['role'], user['role'])}). "
                   "Switch user in the sidebar if you need a different role.")
