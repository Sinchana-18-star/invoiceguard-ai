# Workflow pipeline: state mapping

The pipeline on the **Workflow Pipeline** page (and the overview on the Dashboard) is drawn only from data
the backend already records. No stage state is guessed or stored by the UI.

Sources:

- `S` = `service.workflow_state(ctx, invoice_id)` → the LangGraph checkpoint values (`graph/state.py: InvoiceState`)
- `I` = `service.get_invoice(ctx, invoice_id)` → the invoice row (`status`, `escalation_reason`, …) plus `pending`
  (the open LangGraph `interrupt`, if any)
- `H` = `AuditLog.get_invoice_history(invoice_id)` → audit events, used for "latest event" and timestamps

Implementation: `ui/components/workflow.py: build_stages()`.

| # | Visual stage | LangGraph node(s) | State fields read | Audit events (latest event / timestamp) |
|---|---|---|---|---|
| 1 | Invoice Intake | `intake` | `S.file_hash`, `I.status` | `INVOICE_UPLOADED` |
| 2 | Document Extraction | `extract`, `reextract` | `S.extracted`, `S.extraction_failed`, `S.noop_detected`, `S.attempt`, `S.extraction_strategy`, `S.overall_confidence` | `EXTRACTION_COMPLETED`, `EXTRACTION_RETRIED` |
| 3 | Business Validation | `validate` | `S.validation_result.passed / errors / warnings` | `VALIDATION_PASSED`, `VALIDATION_FAILED` |
| 4 | Agentic Workflow | `action`, `ledger` | `S.action_result.ok / reason`, `S.ledger_result.status` | `RECORD_BUILT`, `RECORD_FAILED`, `LEDGER_*` |
| 5 | Independent Checker | `checker` (+ risk score) | `S.checker_result.passed / reasons / risk` | `CHECKER_PASSED`, `CHECKER_FAILED` |
| 6 | Human Approval | `router` outcome, `request_approval`, `human_approval`, `escalate`, `manual_review` | `I.status`, `I.pending.type`, `S.route`, `S.escalation_reason`, `I.approvals` | `ROUTE_DECIDED`, `APPROVAL_REQUESTED`, `APPROVAL_DENIED`, `INVOICE_ESCALATED`, `FIELD_CORRECTED`, `FLAG_CLEARED` |
| 7 | Finalization | `blocked`, `finalize` | `I.status ∈ {APPROVED, REJECTED, BLOCKED}`, `I.decided_by`, `I.failure_reason` | `INVOICE_APPROVED`, `INVOICE_REJECTED`, `INVOICE_BLOCKED`, `LEDGER_DECISION_RECORDED` |

The `router` node runs after the checker in the real graph. Its decision (approval, re-extract or escalate)
is shown in stage 6 because that is where it takes effect; a re-extraction shows up in stage 2's attempt count.

## Visual states

| Stage | Completed | Active | Failed | Escalated | Pending |
|---|---|---|---|---|---|
| 1 Intake | `S.file_hash` set | `I.status` RECEIVED | – | – | otherwise |
| 2 Extraction | `S.extracted` present | intake done and `I.status` PROCESSING | `S.extraction_failed` | `S.noop_detected` | otherwise |
| 3 Validation | `S.validation_result.passed` | extraction done and PROCESSING | `validation_result.passed == false` | – | otherwise |
| 4 Agentic | `S.action_result.ok` and ledger step ran | validation passed and PROCESSING | `action_result.ok == false` | `ledger_result.status == REGISTERED_ELSEWHERE` | otherwise |
| 5 Checker | `S.checker_result.passed` | agentic done and PROCESSING | `checker_result.passed == false` | – | otherwise |
| 6 Human approval | `I.status` APPROVED / REJECTED | `I.status` AWAITING_APPROVAL | – | `I.status` ESCALATED | otherwise (incl. BLOCKED: never reached) |
| 7 Finalization | `I.status` APPROVED / REJECTED / BLOCKED | – | – | – | otherwise |

Retry count on stage 2: `Attempt {S.attempt} of {spec.bounds.max_iterations}`.
