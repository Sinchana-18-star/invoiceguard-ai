"""Shared LangGraph state. Values are plain JSON types so checkpoints and snapshots stay portable."""
from __future__ import annotations

from typing import Any, TypedDict


class InvoiceState(TypedDict, total=False):
    # identity
    invoice_id: str
    file_hash: str
    file_path: str
    file_name: str
    uploader_id: str

    # extraction (only the extractor and audited manual corrections write these)
    extracted: dict[str, Any]
    confidence: dict[str, float]
    overall_confidence: float
    extraction_strategy: str
    strategy_idx: int
    attempt: int
    raw_text: str
    extraction_failed: bool
    reextract_requested: bool
    noop_detected: bool

    # bounds bookkeeping
    tool_calls: int
    started_at: float
    state_hash: str
    prev_state_hash: str

    # results
    validation_result: dict[str, Any]
    action_result: dict[str, Any]
    ledger_result: dict[str, Any]
    checker_result: dict[str, Any]
    flags: list[str]
    route: str

    # decisions
    approval_status: str | None
    status: str
    escalation_reason: str | None
    failure_reason: str | None
    decided_by: str | None
    decision_reason: str | None
    corrected_by: list[str]
    released_by: str | None
    audit_reference: str
