"""Routing rules - the five loop bounds live here.

Extraction-only smart retry: the deterministic checker is never re-run on unchanged data. We only go
back to extraction when the extraction itself looks unreliable (low confidence) and attempts remain.
"""
from __future__ import annotations

import time

from core.config import WorkflowSpec
from graph.state import InvoiceState


def decide_after_checker(state: InvoiceState, spec: WorkflowSpec, n_strategies: int) -> tuple[str, str | None]:
    b, t = spec.bounds, spec.thresholds
    checker = state.get("checker_result") or {}

    if state.get("tool_calls", 0) > b.max_tool_calls:
        return "escalate", f"TOOL_CALL_LIMIT: {state['tool_calls']} tool calls > {b.max_tool_calls}"
    elapsed = time.time() - state.get("started_at", time.time())
    if elapsed > b.timeout_seconds:
        return "escalate", f"TIMEOUT: automated run took {elapsed:.0f}s > {b.timeout_seconds}s"

    if checker.get("passed"):  # success gate
        released = bool(state.get("released_by"))
        if "PROMPT_INJECTION_SUSPECTED" in state.get("flags", []) and not released:
            return "escalate", "SUSPICIOUS_CONTENT: instruction-like text found in the document; needs manual review"
        risk = checker.get("risk") or {}
        if risk.get("level") == "HIGH" and not released:
            top = ", ".join(s["code"] for s in risk.get("signals", [])[:3])
            return "escalate", f"FRAUD_RISK_HIGH: risk score {risk['score']}/100 ({top})"
        return "request_approval", None

    low_confidence = state.get("overall_confidence", 0.0) < t.low_confidence
    if not low_confidence:
        return "escalate", ("CHECKER_FAILED_HIGH_CONFIDENCE: extraction is reliable "
                            f"({state.get('overall_confidence', 0):.2f}), so the document itself is inconsistent: "
                            + "; ".join(checker.get("reasons", [])[:3]))
    if state.get("attempt", 0) >= b.max_iterations:
        return "escalate", f"MAX_ITERATIONS_REACHED: {state.get('attempt')} extraction attempts"
    if state.get("strategy_idx", 0) + 1 >= n_strategies:
        return "escalate", "NO_MORE_STRATEGIES: checker failed and no further extraction strategy is available"
    return "reextract", None


def after_extract(state: InvoiceState) -> str:
    if state.get("extraction_failed") or state.get("noop_detected"):
        return "escalate"
    return "validate"


def after_validate(state: InvoiceState) -> str:
    return "action" if (state.get("validation_result") or {}).get("passed") else "blocked"


def after_action(state: InvoiceState) -> str:
    return "ledger" if (state.get("action_result") or {}).get("ok") else "blocked"


def after_router(state: InvoiceState) -> str:
    return state["route"]
