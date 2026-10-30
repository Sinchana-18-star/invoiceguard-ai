"""Service layer used by the UI and tests. All state changes go through the LangGraph workflow."""
from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path

from langgraph.types import Command
from sqlalchemy import func, select

from core.authz import decision_errors
from core.context import AppContext
from core.db import (GoodsReceipt, GoodsReceiptItem, Invoice, PurchaseOrder, PurchaseOrderItem, Status, Supplier,
                     User)
from graph.checkpoint import thread_config
from tools.extractor import SUPPORTED_SUFFIXES
from tools.gst import validate_gstin


class WorkflowError(Exception):
    pass


# ---------------------------------------------------------------- submitting and deciding
def submit_invoice(ctx: AppContext, uploader_id: str, file_name: str, data: bytes) -> dict:
    suffix = Path(file_name).suffix.lower()
    if suffix not in SUPPORTED_SUFFIXES:
        raise ValueError(f"Unsupported file type '{suffix}'. Upload PDF, PNG, JPG or JPEG.")
    if not data:
        raise ValueError("The uploaded file is empty")
    with ctx.Session() as s:
        if s.get(User, uploader_id) is None:
            raise PermissionError(f"Unknown user '{uploader_id}'")
        invoice_id = f"INV-{datetime.now(timezone.utc):%Y%m%d}-{uuid.uuid4().hex[:6].upper()}"
        path = ctx.uploads_dir / f"{invoice_id}{suffix}"
        path.write_bytes(data)
        s.add(Invoice(id=invoice_id, uploader_id=uploader_id, file_name=Path(file_name).name, file_path=str(path),
                      status=Status.RECEIVED))
        s.commit()
    ctx.graph.invoke({"invoice_id": invoice_id, "uploader_id": uploader_id, "file_path": str(path),
                      "file_name": Path(file_name).name}, thread_config(invoice_id))
    return get_invoice(ctx, invoice_id)


def workflow_state(ctx: AppContext, invoice_id: str) -> dict:
    return dict(ctx.graph.get_state(thread_config(invoice_id)).values)


def pending_interrupt(ctx: AppContext, invoice_id: str) -> dict | None:
    snapshot = ctx.graph.get_state(thread_config(invoice_id))
    for task in snapshot.tasks:
        for intr in task.interrupts:
            return intr.value
    return None


def decide(ctx: AppContext, invoice_id: str, actor_id: str, action: str, reason: str | None = None,
           corrections: dict[str, str] | None = None) -> dict:
    """Resume the paused workflow with a human decision. Raises PermissionError if not allowed."""
    pending = pending_interrupt(ctx, invoice_id)
    if pending is None:
        raise WorkflowError(f"{invoice_id} is not waiting for a decision")
    if action not in pending["allowed_actions"]:
        raise WorkflowError(f"'{action}' is not allowed now; allowed: {', '.join(pending['allowed_actions'])}")
    if action in ("reject", "escalate", "release") and not (reason or "").strip():
        raise ValueError("A reason is required")
    if action == "correct" and not corrections:
        raise ValueError("No corrections given")
    state = workflow_state(ctx, invoice_id)
    with ctx.Session() as s:
        errors = decision_errors(s, ctx.spec, s.get(Invoice, invoice_id), actor_id, action, state.get("corrected_by"))
        if action == "release" and not (state.get("checker_result") or {}).get("passed"):
            errors.append("NOT_RELEASABLE: only invoices that passed the checker can be released to approval")
    if errors:
        ctx.audit.append_event(invoice_id, "APPROVAL_DENIED", actor_id, {"action": action, "errors": errors})
        raise PermissionError("; ".join(errors))
    ctx.graph.invoke(Command(resume={"actor": actor_id, "action": action, "reason": reason,
                                     "corrections": corrections or {}}), thread_config(invoice_id))
    return get_invoice(ctx, invoice_id)


# ---------------------------------------------------------------- reading
def _loads(text: str | None):
    return json.loads(text) if text else None


def invoice_to_dict(inv: Invoice) -> dict:
    extracted = _loads(inv.extracted_json) or {}
    return {
        "id": inv.id, "status": inv.status, "uploader_id": inv.uploader_id, "file_name": inv.file_name,
        "file_path": inv.file_path, "file_hash": inv.file_hash, "invoice_number": inv.invoice_number,
        "supplier_gstin": inv.supplier_gstin, "supplier_name": inv.supplier_name, "invoice_date": inv.invoice_date,
        "po_number": inv.po_number, "grand_total": inv.grand_total, "extraction_strategy": inv.extraction_strategy,
        "confidence": inv.confidence, "extracted": extracted.get("fields"), "field_confidence": extracted.get("confidence"),
        "validation": _loads(inv.validation_json), "checker": _loads(inv.checker_json),
        "flags": _loads(inv.flags_json) or [], "ledger": _loads(inv.ledger_json), "failure_reason": inv.failure_reason,
        "escalation_reason": inv.escalation_reason, "decided_by": inv.decided_by, "decision_reason": inv.decision_reason,
        "created_at": inv.created_at, "updated_at": inv.updated_at,
        "approvals": [{"manager_id": a.manager_id, "decision": a.decision, "reason": a.reason, "at": a.created_at}
                      for a in inv.approvals],
    }


def get_invoice(ctx: AppContext, invoice_id: str) -> dict:
    with ctx.Session() as s:
        inv = s.get(Invoice, invoice_id)
        if inv is None:
            raise KeyError(invoice_id)
        out = invoice_to_dict(inv)
    out["pending"] = pending_interrupt(ctx, invoice_id)
    return out


def list_invoices(ctx: AppContext, statuses: tuple[str, ...] | None = None, uploader_id: str | None = None) -> list[dict]:
    with ctx.Session() as s:
        q = select(Invoice).order_by(Invoice.created_at.desc())
        if statuses:
            q = q.where(Invoice.status.in_(statuses))
        if uploader_id:
            q = q.where(Invoice.uploader_id == uploader_id)
        return [invoice_to_dict(i) for i in s.scalars(q).all()]


def metrics(ctx: AppContext) -> dict:
    with ctx.Session() as s:
        counts = dict(s.execute(select(Invoice.status, func.count()).group_by(Invoice.status)).all())
        checked = s.scalars(select(Invoice.checker_json).where(Invoice.checker_json.is_not(None))).all()
    verified = sum(1 for c in checked if json.loads(c).get("passed"))
    total = sum(counts.values())
    processed = total - counts.get(Status.RECEIVED, 0) - counts.get(Status.PROCESSING, 0)
    return {"total": total, "verified": verified, "pending": counts.get(Status.AWAITING_APPROVAL, 0),
            "rejected": counts.get(Status.REJECTED, 0), "escalated": counts.get(Status.ESCALATED, 0),
            "approved": counts.get(Status.APPROVED, 0), "blocked": counts.get(Status.BLOCKED, 0),
            "success_rate": (verified / processed) if processed else 0.0, "by_status": counts}


def list_users(ctx: AppContext) -> list[User]:
    with ctx.Session() as s:
        return list(s.scalars(select(User).order_by(User.role, User.id)).all())


# ---------------------------------------------------------------- blockchain ledger
def ledger_info(ctx: AppContext) -> dict:
    if ctx.ledger is None:
        return {"enabled": False, "reason": ctx.ledger_error or "Ledger turned off (INVOICEGUARD_LEDGER=off)"}
    return {"enabled": True, **ctx.ledger.info()}


def simulate_other_organisation_registration(ctx: AppContext, gstin: str, invoice_number: str) -> dict:
    """DEMO ONLY: a second organisation (another buyer or lender on the same local chain) registers an
    invoice first, so the next upload of that invoice here is caught as possible double financing."""
    if ctx.ledger is None or ctx.ledger.mode != "local":
        raise WorkflowError("Simulation is only available on the local demo chain")
    other = ctx.ledger.as_organisation(1)
    result = other.register(gstin, invoice_number)
    ctx.audit.append_event(None, "DEMO_EXTERNAL_REGISTRATION", "demo",
                           {"organisation": other.account, "gstin": gstin, "invoice_number": invoice_number,
                            **result})
    return {**result, "organisation": other.account}


# ---------------------------------------------------------------- master data
def add_supplier(ctx: AppContext, name: str, gstin: str) -> Supplier:
    gstin = gstin.strip().upper()
    problems = validate_gstin(gstin)
    if problems:
        raise ValueError("; ".join(problems))
    with ctx.Session() as s:
        sup = Supplier(name=name.strip(), gstin=gstin, state_code=gstin[:2])
        s.add(sup)
        s.commit()
        return sup


def add_purchase_order(ctx: AppContext, po_number: str, supplier_gstin: str, items: list[dict]) -> None:
    with ctx.Session() as s:
        sup = s.scalar(select(Supplier).where(Supplier.gstin == supplier_gstin.upper()))
        if sup is None:
            raise ValueError(f"Unknown supplier {supplier_gstin}")
        s.add(PurchaseOrder(po_number=po_number.strip(), supplier_id=sup.id, items=[
            PurchaseOrderItem(description=i["description"], quantity=Decimal(str(i["quantity"])),
                              unit_price=Decimal(str(i["unit_price"])), gst_rate=Decimal(str(i["gst_rate"])))
            for i in items]))
        s.commit()


def add_goods_receipt(ctx: AppContext, grn_number: str, po_number: str, items: list[dict]) -> None:
    with ctx.Session() as s:
        po = s.scalar(select(PurchaseOrder).where(PurchaseOrder.po_number == po_number.strip()))
        if po is None:
            raise ValueError(f"Unknown purchase order {po_number}")
        s.add(GoodsReceipt(grn_number=grn_number.strip(), po_id=po.id, items=[
            GoodsReceiptItem(description=i["description"], quantity_received=Decimal(str(i["quantity_received"])))
            for i in items]))
        s.commit()
