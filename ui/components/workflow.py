"""Workflow pipeline: stage model built only from real workflow state (see ui/workflow_mapping.md) and an
SVG renderer. Pure SVG/CSS - no JavaScript, no WebGL."""
from __future__ import annotations

from core.db import Status
from ui.format import esc, money, when

STAGES = [
    ("intake", "Invoice Intake", {"INVOICE_UPLOADED"}),
    ("extraction", "Document Extraction", {"EXTRACTION_COMPLETED", "EXTRACTION_RETRIED"}),
    ("validation", "Business Validation", {"VALIDATION_PASSED", "VALIDATION_FAILED"}),
    ("agentic", "Agentic Workflow", {"RECORD_BUILT", "RECORD_FAILED", "LEDGER_REGISTERED", "LEDGER_ALREADY_REGISTERED",
                                     "LEDGER_DUPLICATE_ELSEWHERE", "LEDGER_SKIPPED"}),
    ("checker", "Independent Checker", {"CHECKER_PASSED", "CHECKER_FAILED"}),
    ("human", "Human Approval", {"ROUTE_DECIDED", "APPROVAL_REQUESTED", "APPROVAL_DENIED", "INVOICE_ESCALATED",
                                 "FIELD_CORRECTED", "FLAG_CLEARED"}),
    ("final", "Finalization", {"INVOICE_APPROVED", "INVOICE_REJECTED", "INVOICE_BLOCKED", "LEDGER_DECISION_RECORDED"}),
]
STATE_STYLE = {  # fill, stroke, text, label
    "completed": ("#E8F5EE", "#23865B", "#23865B", "Completed"),
    "active": ("#EAF1FA", "#3978C5", "#3978C5", "Active"),
    "pending": ("#FFFFFF", "#CBD5E1", "#718096", "Pending"),
    "failed": ("#FAECEC", "#CC5151", "#CC5151", "Failed"),
    "escalated": ("#FBF3E4", "#D99A32", "#9A6A1C", "Escalated"),
}


def build_stages(inv: dict, s: dict, history: list[dict], spec) -> list[dict]:
    status = inv["status"]
    running = status in (Status.RECEIVED, Status.PROCESSING)
    vr, ar, lr, cr = (s.get("validation_result") or {}, s.get("action_result") or {}, s.get("ledger_result") or {},
                      s.get("checker_result") or {})
    pending = inv.get("pending") or {}
    states: dict[str, str] = {}

    states["intake"] = "completed" if s.get("file_hash") else "active" if status == Status.RECEIVED else "pending"
    if s.get("extraction_failed"):
        states["extraction"] = "failed"
    elif s.get("noop_detected"):
        states["extraction"] = "escalated"
    elif s.get("extracted"):
        states["extraction"] = "completed"
    else:
        states["extraction"] = "active" if running and states["intake"] == "completed" else "pending"
    if vr:
        states["validation"] = "completed" if vr.get("passed") else "failed"
    else:
        states["validation"] = "active" if running and states["extraction"] == "completed" else "pending"
    if ar and not ar.get("ok"):
        states["agentic"] = "failed"
    elif lr.get("status") == "REGISTERED_ELSEWHERE":
        states["agentic"] = "escalated"
    elif ar.get("ok") and lr:
        states["agentic"] = "completed"
    else:
        states["agentic"] = "active" if running and states["validation"] == "completed" else "pending"
    if cr:
        states["checker"] = "completed" if cr.get("passed") else "failed"
    else:
        states["checker"] = "active" if running and states["agentic"] == "completed" else "pending"
    states["human"] = {Status.APPROVED: "completed", Status.REJECTED: "completed", Status.AWAITING_APPROVAL: "active",
                       Status.ESCALATED: "escalated"}.get(status, "pending")
    states["final"] = "completed" if status in Status.FINAL else "pending"

    evidence: dict[str, list[str]] = {k: [] for k, _, _ in STAGES}
    errors: dict[str, str | None] = {k: None for k, _, _ in STAGES}
    evidence["intake"] = [f"File: {inv['file_name']}", f"SHA-256: {(s.get('file_hash') or '-')[:24]}…",
                          f"Uploaded by {inv['uploader_id']}"]
    if s.get("extracted"):
        evidence["extraction"] = [f"Strategy: {s.get('extraction_strategy')}",
                                  f"Overall confidence: {s.get('overall_confidence', 0):.2f}"]
    if s.get("extraction_failed") or s.get("noop_detected"):
        errors["extraction"] = s.get("escalation_reason")
    evidence["validation"] = [f"Warning {w['code']}: {w['message']}" for w in vr.get("warnings", [])]
    if vr and not vr.get("passed"):
        errors["validation"] = "; ".join(f"{e['code']}: {e['message']}" for e in vr.get("errors", []))
    if ar.get("record"):
        evidence["agentic"] = [f"Invoice record built: {ar['record'].get('invoice_number')} "
                               f"({money(ar['record'].get('grand_total'))})"]
    if lr:
        evidence["agentic"].append(f"Ledger: {lr.get('status')}" + (f" · tx {lr['tx_hash'][:18]}…" if lr.get("tx_hash") else ""))
    if ar and not ar.get("ok"):
        errors["agentic"] = ar.get("reason")
    elif lr.get("status") == "REGISTERED_ELSEWHERE":
        errors["agentic"] = f"Already registered on chain by {lr.get('registrar')}"
    if cr:
        evidence["checker"] = cr.get("evidence", [])[:8]
        risk = cr.get("risk") or {}
        if risk:
            evidence["checker"].append(f"Fraud risk {risk['score']}/100 ({risk['level']})")
        if not cr.get("passed"):
            errors["checker"] = "; ".join(cr.get("reasons", [])[:4])
    if s.get("route"):
        evidence["human"].append(f"Router decision: {s['route']}")
    if pending:
        evidence["human"].append(f"Waiting for: {pending['type'].replace('_', ' ')} "
                                 f"(allowed: {', '.join(pending['allowed_actions'])})")
    evidence["human"] += [f"{a['manager_id']}: {a['decision']}" + (f" ({a['reason']})" if a["reason"] else "")
                          for a in inv.get("approvals", [])]
    if status == Status.ESCALATED:
        errors["human"] = inv.get("escalation_reason")
    if status in Status.FINAL:
        evidence["final"] = [f"Outcome: {status}"] + ([f"Decided by {inv['decided_by']}"] if inv.get("decided_by") else [])
        if status in (Status.BLOCKED, Status.REJECTED):
            errors["final"] = inv.get("failure_reason") or inv.get("decision_reason")

    stages = []
    for key, name, events in STAGES:
        latest = next((e for e in reversed(history) if e["event_type"] in events), None)
        stage = {"key": key, "name": name, "state": states[key], "evidence": evidence[key], "error": errors[key],
                 "latest_event": latest["event_type"] if latest else None,
                 "timestamp": when(latest["timestamp"]) if latest else None}
        if key == "extraction":
            stage["retry"] = f"Attempt {s.get('attempt', 0)} of {spec.bounds.max_iterations}"
        stages.append(stage)
    return stages


def pipeline_svg(stages: list[dict], selected: str | None = None) -> str:
    """stages: [{'key','name','state', optional 'caption'}]. Returns escaped SVG markup."""
    n, w, h, gap = len(stages), 128, 74, 18
    total = n * w + (n - 1) * gap + 20
    parts = [f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {total} 128" preserveAspectRatio="xMinYMin meet">']
    for i, st_ in enumerate(stages):
        x = 10 + i * (w + gap)
        fill, stroke, text, label = STATE_STYLE[st_["state"]]
        if i:
            done = stages[i - 1]["state"] == "completed"
            parts.append(f'<line x1="{x - gap}" y1="{20 + h / 2}" x2="{x}" y2="{20 + h / 2}" '
                         f'stroke="{"#23865B" if done else "#CBD5E1"}" stroke-width="2"/>')
        sw = 3 if st_["key"] == selected else 1.5
        dash = ' stroke-dasharray="4 3"' if st_["state"] == "pending" else ""
        parts.append(f'<rect x="{x}" y="20" width="{w}" height="{h}" rx="6" fill="{fill}" stroke="{stroke}" '
                     f'stroke-width="{sw}"{dash}/>')
        parts.append(f'<text x="{x + 10}" y="40" font-size="10" font-weight="600" fill="#718096" '
                     f'font-family="Inter, sans-serif">STEP {i + 1}</text>')
        words, line, lines = st_["name"].split(), "", []
        for wd in words:
            if len(line + " " + wd) > 17 and line:
                lines.append(line)
                line = wd
            else:
                line = (line + " " + wd).strip()
        lines.append(line)
        for j, ln in enumerate(lines[:2]):
            parts.append(f'<text x="{x + 10}" y="{57 + j * 14}" font-size="12" font-weight="600" fill="#182638" '
                         f'font-family="Inter, sans-serif">{esc(ln)}</text>')
        parts.append(f'<text x="{x + 10}" y="{20 + h + 18}" font-size="11" font-weight="600" fill="{text}" '
                     f'font-family="Inter, sans-serif">{esc(st_.get("caption") or label)}</text>')
    parts.append("</svg>")
    return f'<div class="ig-pipeline" role="img" aria-label="Invoice verification pipeline">{"".join(parts)}</div>'
