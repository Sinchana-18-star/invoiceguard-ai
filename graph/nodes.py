"""LangGraph node functions. Each node does one job, writes the audit log and returns a state update."""
from __future__ import annotations

import copy
import hashlib
import json
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal

from langgraph.types import Command, interrupt

from core.authz import decision_errors
from core.db import Approval, Invoice, Status
from graph.router import decide_after_checker
from graph.state import InvoiceState
from tools.action import build_invoice_record, dumps
from tools.checker import run_checker
from tools.models import ExtractedInvoice, ExtractionResult, LineItem, overall_confidence
from tools.risk import assess_risk
from tools.validator import validate

if TYPE_CHECKING:
    from core.context import AppContext

SYSTEM = "system"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def state_hash(extracted: dict) -> str:
    return hashlib.sha256(json.dumps(extracted, sort_keys=True, default=str).encode()).hexdigest()


def apply_corrections(extracted: dict, confidence: dict, corrections: dict[str, str]) -> list[dict]:
    """Apply 'field' or 'line_items.<i>.<field>' corrections in place. Returns the change list."""
    changes = []
    for path, new in corrections.items():
        new_value = None if new in ("", None) else str(new).strip()
        parts = path.split(".")
        if parts[0] == "line_items" and len(parts) == 3:
            idx, field = int(parts[1]), parts[2]
            if field not in LineItem.model_fields:
                raise ValueError(f"Unknown line item field '{field}'")
            while len(extracted["line_items"]) <= idx:
                extracted["line_items"].append(LineItem().model_dump(mode="json"))
            old = extracted["line_items"][idx].get(field)
            extracted["line_items"][idx][field] = new_value
            confidence["line_items"] = 1.0
        elif len(parts) == 1 and parts[0] in ExtractedInvoice.model_fields and parts[0] != "line_items":
            old = extracted.get(path)
            extracted[path] = new_value
            confidence[path] = 1.0
        else:
            raise ValueError(f"Unknown field '{path}'")
        if str(old) != str(new_value):
            changes.append({"field": path, "old": old, "new": new_value})
    ExtractedInvoice.model_validate(extracted)  # reject corrections that are not valid numbers etc.
    return changes


def build_nodes(ctx: "AppContext") -> dict:
    spec, audit = ctx.spec, ctx.audit

    def update_invoice(invoice_id: str, **fields) -> None:
        with ctx.Session() as s:
            inv = s.get(Invoice, invoice_id)
            for k, v in fields.items():
                setattr(inv, k, v)
            s.commit()

    def snapshotting(name, fn):
        def wrapper(state: InvoiceState):
            out = fn(state)
            update = out.update if isinstance(out, Command) else out
            ctx.write_snapshot({**state, **(update or {})}, node=name)
            return out
        wrapper.__name__ = name
        return wrapper

    # ------------------------------------------------------------------ intake
    def intake(state: InvoiceState) -> dict:
        path = Path(state["file_path"])
        file_hash = sha256_file(path)
        update_invoice(state["invoice_id"], file_hash=file_hash, status=Status.PROCESSING)
        ev = audit.append_event(state["invoice_id"], "INVOICE_UPLOADED", state["uploader_id"],
                                {"file_name": state.get("file_name"), "file_hash": file_hash, "bytes": path.stat().st_size})
        return {"file_hash": file_hash, "status": Status.PROCESSING, "attempt": 0, "strategy_idx": 0, "tool_calls": 0,
                "started_at": time.time(), "flags": [], "corrected_by": [], "approval_status": None,
                "audit_reference": ev["event_id"]}

    # ------------------------------------------------------------------ extraction
    def extract(state: InvoiceState) -> dict:
        order = ctx.strategy_order
        idx, attempt, calls = state.get("strategy_idx", 0), state.get("attempt", 0), state.get("tool_calls", 0)
        result: ExtractionResult | None = None
        while idx < len(order) and attempt < spec.bounds.max_iterations:
            name = order[idx]
            attempt += 1
            calls += 1
            try:
                res = ctx.strategies[name](Path(state["file_path"]))
            except Exception as e:  # a broken strategy must not crash the workflow
                res = ExtractionResult.unavailable(name, f"strategy error: {e.__class__.__name__}: {e}")
            if res.available and res.raw_text.strip() and res.invoice.has_any_field():
                result = res
                break
            audit.append_event(state["invoice_id"], "EXTRACTION_RETRIED", SYSTEM,
                               {"strategy": name, "attempt": attempt, "reason": res.notes or ["no text extracted"],
                                "next_strategy": order[idx + 1] if idx + 1 < len(order) else None})
            idx += 1

        base = {"attempt": attempt, "tool_calls": calls, "strategy_idx": idx, "reextract_requested": False,
                "noop_detected": False}
        if result is None:
            had_previous = bool(state.get("extracted"))
            reason = ("NO_MORE_STRATEGIES: no further extraction strategy could read the document" if had_previous
                      else "EXTRACTION_FAILED: no extraction strategy could read the document")
            return {**base, "extraction_failed": True, "escalation_reason": reason}

        extracted = result.invoice.model_dump(mode="json")
        new_hash = state_hash(extracted)
        noop = bool(state.get("reextract_requested")) and new_hash == state.get("state_hash")
        audit.append_event(state["invoice_id"], "EXTRACTION_COMPLETED", SYSTEM, {
            "strategy": result.strategy, "attempt": attempt, "overall_confidence": result.overall_confidence,
            "low_confidence_fields": sorted(k for k, v in result.confidence.items() if v < spec.thresholds.low_confidence),
            "state_hash": new_hash, "no_op": noop})
        update_invoice(state["invoice_id"], extraction_strategy=result.strategy, confidence=result.overall_confidence,
                       extracted_json=dumps({"fields": extracted, "confidence": result.confidence}))
        update = {**base, "extracted": extracted, "confidence": result.confidence,
                  "overall_confidence": result.overall_confidence, "extraction_strategy": result.strategy,
                  "raw_text": result.raw_text[:20000], "extraction_failed": False,
                  "prev_state_hash": state.get("state_hash"), "state_hash": new_hash}
        if noop:
            update.update(noop_detected=True, escalation_reason="NO_OP: re-extraction produced identical data "
                                                                "(state hash unchanged); stopping retries")
        return update

    # ------------------------------------------------------------------ validation
    def validate_node(state: InvoiceState) -> dict:
        inv = ExtractedInvoice.model_validate(state["extracted"])
        with ctx.Session() as s:
            result = validate(s, inv, raw_text=state.get("raw_text", ""), spec=spec, invoice_id=state["invoice_id"],
                              file_hash=state.get("file_hash"))
        data = result.model_dump(mode="json")
        flags = sorted(set(state.get("flags", [])) | set(result.flags))
        audit.append_event(state["invoice_id"], "VALIDATION_PASSED" if result.passed else "VALIDATION_FAILED", SYSTEM,
                           {"errors": data["errors"], "warnings": data["warnings"], "flags": result.flags})
        # also persists the fields being validated, so audited manual corrections show up in the UI
        update_invoice(state["invoice_id"], validation_json=dumps(data), flags_json=dumps(flags),
                       extracted_json=dumps({"fields": state["extracted"], "confidence": state.get("confidence", {})}),
                       extraction_strategy=state.get("extraction_strategy"), confidence=state.get("overall_confidence"))
        return {"validation_result": data, "flags": flags}

    # ------------------------------------------------------------------ action tool
    def action(state: InvoiceState) -> dict:
        inv = ExtractedInvoice.model_validate(state["extracted"])
        with ctx.Session() as s:
            result = build_invoice_record(s, state["invoice_id"], inv)
        audit.append_event(state["invoice_id"], "RECORD_BUILT" if result["ok"] else "RECORD_FAILED", SYSTEM, result)
        return {"action_result": result, "tool_calls": state.get("tool_calls", 0) + 1}

    # ------------------------------------------------------------------ shared blockchain ledger
    def ledger(state: InvoiceState) -> dict:
        record = (state.get("action_result") or {}).get("record") or {}
        if ctx.ledger is None:
            result = {"status": "DISABLED", "reason": ctx.ledger_error or "ledger turned off"}
        else:
            try:
                result = ctx.ledger.register(record["supplier_gstin"], record["invoice_number"])
            except Exception as e:  # chain unavailable: never block the business workflow
                result = {"status": "UNAVAILABLE", "reason": f"{e.__class__.__name__}: {e}"}
        event = {"REGISTERED": "LEDGER_REGISTERED", "ALREADY_OURS": "LEDGER_ALREADY_REGISTERED",
                 "REGISTERED_ELSEWHERE": "LEDGER_DUPLICATE_ELSEWHERE"}.get(result["status"], "LEDGER_SKIPPED")
        audit.append_event(state["invoice_id"], event, SYSTEM, result)
        flags = state.get("flags", [])
        if result["status"] == "REGISTERED_ELSEWHERE":
            flags = sorted(set(flags) | {"DOUBLE_FINANCING_SUSPECTED"})
        update_invoice(state["invoice_id"], ledger_json=dumps(result), flags_json=dumps(flags))
        return {"ledger_result": result, "flags": flags}

    # ------------------------------------------------------------------ independent checker
    def checker(state: InvoiceState) -> dict:
        inv = ExtractedInvoice.model_validate(state["extracted"])
        with ctx.Session() as s:
            result = run_checker(s, inv, spec)
            data = result.model_dump(mode="json")
            # Fraud risk is scored next to the checker but never changes its pass/fail verdict.
            data["risk"] = assess_risk(s, inv, invoice_id=state["invoice_id"], flags=state.get("flags", []),
                                       validation=state.get("validation_result") or {}, checker=data, spec=spec,
                                       ledger=state.get("ledger_result"))
        audit.append_event(state["invoice_id"], "CHECKER_PASSED" if result.passed else "CHECKER_FAILED", SYSTEM,
                           {"reasons": result.reasons, "calculated_values": result.calculated_values,
                            "warnings": result.warnings, "risk_score": data["risk"]["score"],
                            "risk_level": data["risk"]["level"]})
        update_invoice(state["invoice_id"], checker_json=dumps(data))
        return {"checker_result": data, "tool_calls": state.get("tool_calls", 0) + 1}

    # ------------------------------------------------------------------ conditional router
    def router(state: InvoiceState) -> dict:
        route, reason = decide_after_checker(state, spec, len(ctx.strategy_order))
        audit.append_event(state["invoice_id"], "ROUTE_DECIDED", SYSTEM,
                           {"route": route, "reason": reason, "attempt": state.get("attempt"),
                            "tool_calls": state.get("tool_calls"), "confidence": state.get("overall_confidence")})
        return {"route": route, "escalation_reason": reason}

    def reextract(state: InvoiceState) -> dict:
        order, idx = ctx.strategy_order, state.get("strategy_idx", 0)
        audit.append_event(state["invoice_id"], "EXTRACTION_RETRIED", SYSTEM, {
            "from_strategy": order[idx], "to_strategy": order[idx + 1], "attempt": state.get("attempt"),
            "reason": f"checker failed and extraction confidence {state.get('overall_confidence', 0):.2f} "
                      f"< {spec.thresholds.low_confidence}"})
        return {"strategy_idx": idx + 1, "reextract_requested": True}

    # ------------------------------------------------------------------ human approval
    def request_approval(state: InvoiceState) -> dict:
        update_invoice(state["invoice_id"], status=Status.AWAITING_APPROVAL, escalation_reason=None)
        audit.append_event(state["invoice_id"], "APPROVAL_REQUESTED", SYSTEM,
                           {"approver_role": spec.approver, "flags": state.get("flags", [])})
        return {"status": Status.AWAITING_APPROVAL, "approval_status": "PENDING", "escalation_reason": None}

    def _record_decision(invoice_id: str, actor: str, action_name: str, reason: str | None) -> None:
        with ctx.Session() as s:
            s.add(Approval(invoice_id=invoice_id, manager_id=actor, decision=action_name, reason=reason))
            s.commit()

    def _correction_update(state: InvoiceState, actor: str, corrections: dict) -> dict:
        extracted = copy.deepcopy(state["extracted"])
        confidence = dict(state.get("confidence", {}))
        changes = apply_corrections(extracted, confidence, corrections)
        for c in changes:
            audit.append_event(state["invoice_id"], "FIELD_CORRECTED", actor, c)
        base_strategy = state.get("extraction_strategy", "").split("+")[0]
        return {"extracted": extracted, "confidence": confidence, "overall_confidence": overall_confidence(confidence),
                "extraction_strategy": f"{base_strategy}+manual_correction",
                "corrected_by": sorted(set(state.get("corrected_by", [])) | {actor}),
                "prev_state_hash": state.get("state_hash"), "state_hash": state_hash(extracted),
                "started_at": time.time(), "tool_calls": 0, "status": Status.PROCESSING, "approval_status": None}

    def human_approval(state: InvoiceState) -> Command[Literal["finalize", "escalate", "validate", "human_approval"]]:
        decision = interrupt({"type": "approval", "invoice_id": state["invoice_id"],
                              "allowed_actions": ["approve", "reject", "escalate", "correct"]})
        actor, act, reason = decision.get("actor"), decision.get("action"), decision.get("reason")
        with ctx.Session() as s:
            errors = decision_errors(s, spec, s.get(Invoice, state["invoice_id"]), actor, act, state.get("corrected_by"))
        if act not in ("approve", "reject", "escalate", "correct"):
            errors.append(f"UNKNOWN_ACTION: {act}")
        if act in ("reject", "escalate") and not reason:
            errors.append("REASON_REQUIRED")
        if errors:
            audit.append_event(state["invoice_id"], "APPROVAL_DENIED", actor or "unknown", {"action": act, "errors": errors})
            return Command(goto="human_approval")

        _record_decision(state["invoice_id"], actor, act, reason)
        if act == "approve":
            return Command(goto="finalize", update={"status": Status.APPROVED, "approval_status": "APPROVED",
                                                    "decided_by": actor, "decision_reason": reason})
        if act == "reject":
            return Command(goto="finalize", update={"status": Status.REJECTED, "approval_status": "REJECTED",
                                                    "decided_by": actor, "decision_reason": reason})
        if act == "escalate":
            return Command(goto="escalate", update={"approval_status": "ESCALATED",
                                                    "escalation_reason": f"MANAGER_ESCALATED: {reason}"})
        return Command(goto="validate", update=_correction_update(state, actor, decision.get("corrections") or {}))

    # ------------------------------------------------------------------ escalation + manual review
    def escalate(state: InvoiceState) -> dict:
        reason = state.get("escalation_reason") or "ESCALATED"
        update_invoice(state["invoice_id"], status=Status.ESCALATED, escalation_reason=reason)
        audit.append_event(state["invoice_id"], "INVOICE_ESCALATED", SYSTEM, {"reason": reason})
        return {"status": Status.ESCALATED}

    def manual_review(state: InvoiceState) -> Command[Literal["finalize", "validate", "request_approval", "manual_review"]]:
        decision = interrupt({"type": "manual_review", "invoice_id": state["invoice_id"],
                              "allowed_actions": ["correct", "reject", "release"]})
        actor, act, reason = decision.get("actor"), decision.get("action"), decision.get("reason")
        with ctx.Session() as s:
            errors = decision_errors(s, spec, s.get(Invoice, state["invoice_id"]), actor, act)
        if act not in ("correct", "reject", "release"):
            errors.append(f"UNKNOWN_ACTION: {act}")
        if act in ("reject", "release") and not reason:
            errors.append("REASON_REQUIRED")
        if act == "release" and not (state.get("checker_result") or {}).get("passed"):
            errors.append("NOT_RELEASABLE: only invoices that passed the checker can be released to approval")
        if errors:
            audit.append_event(state["invoice_id"], "APPROVAL_DENIED", actor or "unknown", {"action": act, "errors": errors})
            return Command(goto="manual_review")

        _record_decision(state["invoice_id"], actor, act, reason)
        if act == "reject":
            return Command(goto="finalize", update={"status": Status.REJECTED, "approval_status": "REJECTED",
                                                    "decided_by": actor, "decision_reason": reason})
        if act == "release":
            audit.append_event(state["invoice_id"], "FLAG_CLEARED", actor, {"flags": state.get("flags", []), "reason": reason})
            return Command(goto="request_approval", update={
                "released_by": actor, "corrected_by": sorted(set(state.get("corrected_by", [])) | {actor})})
        return Command(goto="validate", update=_correction_update(state, actor, decision.get("corrections") or {}))

    # ------------------------------------------------------------------ terminal
    def blocked(state: InvoiceState) -> dict:
        vr = state.get("validation_result") or {}
        if vr and not vr.get("passed"):
            reason = "; ".join(f"{e['code']}: {e['message']}" for e in vr.get("errors", []))
        else:
            reason = (state.get("action_result") or {}).get("reason", "BLOCKED")
        return {"status": Status.BLOCKED, "failure_reason": reason}

    def finalize(state: InvoiceState) -> dict:
        status = state["status"]
        update_invoice(state["invoice_id"], status=status, failure_reason=state.get("failure_reason"),
                       decided_by=state.get("decided_by"), decision_reason=state.get("decision_reason"))
        event = {Status.APPROVED: "INVOICE_APPROVED", Status.REJECTED: "INVOICE_REJECTED",
                 Status.BLOCKED: "INVOICE_BLOCKED"}[status]
        audit.append_event(state["invoice_id"], event, state.get("decided_by") or SYSTEM,
                           {"reason": state.get("decision_reason") or state.get("failure_reason")})
        ledger_result = state.get("ledger_result") or {}
        if status in (Status.APPROVED, Status.REJECTED) and ctx.ledger is not None \
                and ledger_result.get("status") in ("REGISTERED", "ALREADY_OURS"):
            # Anchor the human decision together with the current audit-log head hash on chain.
            decision_hash = hashlib.sha256(f"{state['invoice_id']}|{status}|{state.get('decided_by')}|"
                                           f"{audit.head_hash()}".encode()).digest()
            try:
                tx = ctx.ledger.record_decision(ledger_result["invoice_key"], status == Status.APPROVED, decision_hash)
                ledger_result = {**ledger_result, "decision": status, "decision_hash": decision_hash.hex(),
                                 "decision_tx": tx}
                update_invoice(state["invoice_id"], ledger_json=dumps(ledger_result))
                audit.append_event(state["invoice_id"], "LEDGER_DECISION_RECORDED", SYSTEM,
                                   {"decision": status, "decision_hash": decision_hash.hex(), **tx})
            except Exception as e:
                audit.append_event(state["invoice_id"], "LEDGER_SKIPPED", SYSTEM,
                                   {"reason": f"{e.__class__.__name__}: {e}"})
            return {"ledger_result": ledger_result}
        return {}

    nodes = {"intake": intake, "extract": extract, "validate": validate_node, "action": action, "ledger": ledger,
             "checker": checker,
             "router": router, "reextract": reextract, "request_approval": request_approval,
             "human_approval": human_approval, "escalate": escalate, "manual_review": manual_review,
             "blocked": blocked, "finalize": finalize}
    return {name: snapshotting(name, fn) for name, fn in nodes.items()}
