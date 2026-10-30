"""Formatting helpers. All invoice-derived text is untrusted: escape it before any HTML rendering."""
from __future__ import annotations

import html
from datetime import datetime
from decimal import Decimal, InvalidOperation


def esc(value) -> str:
    """HTML-escape anything that came from an invoice, the LLM, or a user."""
    return html.escape("" if value is None else str(value), quote=True)


def to_decimal(value) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None


def indian_group(whole: str) -> str:
    if len(whole) <= 3:
        return whole
    head, tail = whole[:-3], whole[-3:]
    groups = []
    while len(head) > 2:
        groups.insert(0, head[-2:])
        head = head[:-2]
    if head:
        groups.insert(0, head)
    return ",".join(groups + [tail])


def money(value, prefix: str = "Rs ") -> str:
    """Rs 4,72,000 / Rs 2,336.40 - Indian digit grouping, Decimal only (never float)."""
    d = to_decimal(value)
    if d is None:
        return "-"
    d = d.quantize(Decimal("0.01"))
    sign = "-" if d < 0 else ""
    whole, frac = f"{abs(d):.2f}".split(".")
    return f"{sign}{prefix}{indian_group(whole)}" + ("" if frac == "00" else f".{frac}")


def when(value) -> str:
    if not value:
        return "-"
    if isinstance(value, datetime):
        return value.strftime("%d %b %Y, %H:%M")
    s = str(value)
    try:
        return datetime.fromisoformat(s).strftime("%d %b %Y, %H:%M:%S")
    except ValueError:
        return s[:19]


_MD_SPECIAL = "\\`*_{}[]()<>#+-.!|~$"


def md_safe(value) -> str:
    """Escape Markdown so untrusted text in labels/messages can't create links, images or formatting."""
    return "".join("\\" + ch if ch in _MD_SPECIAL else ch for ch in ("" if value is None else str(value)))


def render_svg_markup(markup: str) -> None:
    """st.html sanitises out <svg> (and data: images). For our own generated SVG we use st.markdown with raw
    HTML instead. Callers MUST esc() every invoice-, LLM- or user-derived string placed inside `markup`."""
    import streamlit as st

    st.markdown(markup, unsafe_allow_html=True)


def initials(name: str) -> str:
    parts = [p for p in name.split(" (")[0].split() if p[:1].isalpha()]
    return "".join(p[0] for p in parts[:2]).upper() or "?"
