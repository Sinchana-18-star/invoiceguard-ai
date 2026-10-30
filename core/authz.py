"""Who may decide on an invoice: role, separation of duties, approval limits, maker-checker."""
from __future__ import annotations

from sqlalchemy.orm import Session

from core.config import WorkflowSpec
from core.db import Invoice, Status, User


def decision_errors(session: Session, spec: WorkflowSpec, invoice: Invoice, actor_id: str, action: str,
                    corrected_by: list[str] | None = None) -> list[str]:
    user = session.get(User, actor_id)
    if user is None:
        return [f"UNKNOWN_USER: '{actor_id}'"]
    errors = []
    if user.role != spec.approver:
        errors.append(f"ROLE_NOT_AUTHORISED: role '{user.role}' cannot decide on invoices (requires '{spec.approver}')")
    if actor_id == invoice.uploader_id:
        errors.append("SEPARATION_OF_DUTIES: the uploader cannot decide on their own invoice")
    if action == "approve":
        if invoice.status != Status.AWAITING_APPROVAL:
            errors.append(f"NOT_ELIGIBLE: invoice status is {invoice.status}, not {Status.AWAITING_APPROVAL}")
        if user.approval_limit is None or invoice.grand_total is None or invoice.grand_total > user.approval_limit:
            errors.append(f"APPROVAL_LIMIT_EXCEEDED: invoice total {invoice.grand_total} exceeds "
                          f"{user.name}'s approval limit {user.approval_limit}")
        if corrected_by and actor_id in corrected_by:
            errors.append("MAKER_CHECKER: a manager who corrected this invoice cannot also approve it")
    return errors
