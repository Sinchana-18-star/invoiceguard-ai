# InvoiceGuard AI - pre-deployment test summary

Generated 2026-10-30 15:41. **65 passed, 0 failed, 0 skipped** of 65 tests. Deployment is ALLOWED.

| Scenario | Bound / control | Result |
|---|---|---|
| Valid invoice reaches human approval | Success gate | PASS |
| Missing required field is blocked (bad input) | Failure path | PASS |
| Arithmetic mismatch, high confidence: escalate, no pointless retry | Escalation condition | PASS |
| Exact duplicate invoice blocked | Failure path | PASS |
| Same file uploaded twice blocked | Failure path | PASS |
| Near-duplicate flagged for the human, not rejected | Escalation input | PASS |
| Sequential invoice is not a false duplicate | Precision | PASS |
| Invoice above Rs 5,00,000 blocked | Budget limit | PASS |
| Low-confidence failures stop after 3 attempts | Max iterations | PASS |
| Unchanged state hash stops retries | No-op condition | PASS |
| Manager rejection stored in DB + audit | Human approval | PASS |
| Prompt injection cannot approve | Escalation condition | PASS |
| High fraud-risk invoice escalated | Escalation condition | PASS |
| Same invoice registered by another organisation on chain | Escalation condition | PASS |
| App crash while awaiting approval, then resume | Checkpointing | PASS |
| Uploader cannot approve own invoice | Separation of duties | PASS |
| Manager approval limit enforced | Budget limit | PASS |
| Correction re-runs validation + checker; maker-checker | Human approval | PASS |
| Blockchain unavailable does not block the workflow | Resilience | PASS |
| Tampered audit log is detected | Audit | PASS |

Full per-test detail: `reports/test_report.html`.
