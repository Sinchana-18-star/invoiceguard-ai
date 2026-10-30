"""Audit-event timeline. Events after the first broken entry (as reported by the backend's verify_chain())
are marked unverified; nothing is re-hashed in the UI."""
from __future__ import annotations

import json

import streamlit as st

from ui.format import esc, when

FRIENDLY = {
    "INVOICE_UPLOADED": "Invoice uploaded", "EXTRACTION_COMPLETED": "Extraction completed",
    "EXTRACTION_RETRIED": "Extraction retried", "VALIDATION_PASSED": "Validation passed",
    "VALIDATION_FAILED": "Validation failed", "RECORD_BUILT": "Invoice record built",
    "RECORD_FAILED": "Record could not be built", "LEDGER_REGISTERED": "Fingerprint registered on chain",
    "LEDGER_ALREADY_REGISTERED": "Already registered by us on chain",
    "LEDGER_DUPLICATE_ELSEWHERE": "Registered by another organisation", "LEDGER_SKIPPED": "Ledger step skipped",
    "CHECKER_PASSED": "Independent checker passed", "CHECKER_FAILED": "Independent checker failed",
    "ROUTE_DECIDED": "Workflow routed", "APPROVAL_REQUESTED": "Approval requested",
    "APPROVAL_DENIED": "Decision refused by authorisation rules", "FIELD_CORRECTED": "Field corrected",
    "FLAG_CLEARED": "Flag released by reviewer", "INVOICE_ESCALATED": "Escalated for manual review",
    "INVOICE_APPROVED": "Approved", "INVOICE_REJECTED": "Rejected", "INVOICE_BLOCKED": "Blocked",
    "LEDGER_DECISION_RECORDED": "Decision anchored on chain",
}
BAD = {"VALIDATION_FAILED", "CHECKER_FAILED", "RECORD_FAILED", "LEDGER_DUPLICATE_ELSEWHERE", "APPROVAL_DENIED",
       "INVOICE_REJECTED", "INVOICE_BLOCKED", "INVOICE_ESCALATED"}
OK = {"VALIDATION_PASSED", "CHECKER_PASSED", "INVOICE_APPROVED", "LEDGER_REGISTERED", "LEDGER_DECISION_RECORDED"}


def friendly(event_type: str) -> str:
    return FRIENDLY.get(event_type, event_type.replace("_", " ").title())


def timeline(events: list[dict], chain: dict | None = None, show_hashes: bool = False) -> None:
    broken_from = (chain or {}).get("first_broken_seq") if chain and not chain.get("intact") else None
    items = []
    for e in events:
        unverified = broken_from is not None and e.get("seq", 0) >= broken_from
        cls = "ig-tl-bad" if (e["event_type"] in BAD or unverified) else "ig-tl-ok" if e["event_type"] in OK else ""
        detail = json.dumps(e.get("event_data") or {}, default=str)
        detail = detail if len(detail) < 260 else detail[:257] + "..."
        verified = ("<span class='ig-badge ig-b-danger'>Unverified</span> " if unverified else
                    "<span class='ig-badge ig-b-success'>Chain verified</span> " if chain and chain.get("intact") else "")
        hashes = (f"<div class='ig-hash'>prev {esc(e.get('previous_hash', '')[:16])}… · "
                  f"hash {esc(e.get('current_hash', '')[:16])}…</div>" if show_hashes and e.get("current_hash") else "")
        items.append(f"<div class='ig-tl-item {cls}'><div class='ig-tl-head'>{verified}{esc(friendly(e['event_type']))}"
                     f"</div><div class='ig-tl-meta'>#{esc(e.get('seq'))} · {esc(when(e.get('timestamp')))} · "
                     f"by {esc(e.get('actor'))}</div><div class='ig-tl-meta'>{esc(detail)}</div>{hashes}</div>")
    st.html(f"<div class='ig-timeline'>{''.join(items)}</div>" if items else "<div class='ig-missing'>No events</div>")
