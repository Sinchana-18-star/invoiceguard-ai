"""Status, verification, risk and confidence indicators (HTML snippets, always escaped)."""
from __future__ import annotations

from core.db import Status
from ui.format import esc

STATUS_STYLE = {
    Status.RECEIVED: ("Received", "neutral"),
    Status.PROCESSING: ("Processing", "info"),
    Status.BLOCKED: ("Blocked", "danger"),
    Status.AWAITING_APPROVAL: ("Pending approval", "warning"),
    Status.ESCALATED: ("Escalated", "warning"),
    Status.APPROVED: ("Approved", "success"),
    Status.REJECTED: ("Rejected", "danger"),
}
KIND_COLOR = {"success": "#23865B", "warning": "#D99A32", "danger": "#CC5151", "info": "#3978C5", "neutral": "#718096"}


def badge(label: str, kind: str = "neutral") -> str:
    return f'<span class="ig-badge ig-b-{kind}">{esc(label)}</span>'


def status_label(status: str) -> str:
    return STATUS_STYLE.get(status, (status, "neutral"))[0]


def status_badge(status: str) -> str:
    label, kind = STATUS_STYLE.get(status, (status, "neutral"))
    return badge(label, kind)


def verification(inv: dict) -> tuple[str, str]:
    """Verification state derived only from what the backend recorded. Never 'Verified' while the
    workflow is still running (e.g. right after a correction)."""
    status, checker = inv["status"], inv.get("checker")
    if status in (Status.RECEIVED, Status.PROCESSING):
        return "Verification pending", "info"
    if status == Status.BLOCKED and not checker:
        return "Failed validation", "danger"
    if checker is None:
        return "Not verified", "neutral"
    return ("Checker passed", "success") if checker.get("passed") else ("Checker failed", "danger")


def verification_badge(inv: dict) -> str:
    return badge(*verification(inv))


def risk_of(inv: dict) -> dict:
    return ((inv.get("checker") or {}).get("risk")) or {}


def risk_badge(inv: dict) -> str:
    risk = risk_of(inv)
    if not risk:
        return badge("Not scored", "neutral")
    kind = {"HIGH": "danger", "MEDIUM": "warning", "LOW": "success"}[risk["level"]]
    return badge(f"Risk {risk['score']} · {risk['level'].title()}", kind)


def confidence_kind(conf: float | None, spec) -> str:
    if conf is None:
        return "neutral"
    t = spec.thresholds
    return "success" if conf >= t.green_confidence else "warning" if conf >= t.amber_confidence else "danger"


def confidence_badge(conf: float | None, spec) -> str:
    if conf is None:
        return badge("n/a", "neutral")
    return badge(f"{conf:.2f}", confidence_kind(conf, spec))
