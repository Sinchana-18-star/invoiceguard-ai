# InvoiceGuard AI

Agentic enterprise invoice verification and approval, built for the hackathon problem statement
**"Build and Deploy a Pre-Tested Enterprise Workflow"**.

An employee uploads a supplier invoice (PDF or image), or n8n forwards one from a mailbox. A LangGraph
workflow extracts it, validates it, records it, fingerprints it on a **shared blockchain registry**, has an
**independent deterministic checker** verify the GST maths and the PO/GRN three-way match, scores its
**fraud risk with explained reasons**, and then **pauses for a human accounts manager**. Nothing is paid
automatically, and the LLM can never approve an invoice or change a verified amount.

## What makes it different

| | |
|---|---|
| **Pre-tested deployment gate** | `python scripts/deploy.py` runs the full test suite, writes `reports/TEST_SUMMARY.md`, and refuses to start the app if any test fails. |
| **Extraction-only smart retry** | The checker is deterministic, so it is never retried on unchanged data. Only the *extraction* is retried, and only when its confidence is low. |
| **Explainable fraud score** | 0-100 score from fixed rules (near-duplicate, price inflation, invoice splitting, just-below-limit, urgent terms, double financing…), each with a plain-English reason. HIGH risk is escalated. |
| **Blockchain double-financing check** | A Solidity `InvoiceRegistry` stores only SHA-256 fingerprints. If another organisation already registered the same invoice, it is escalated. Human decisions are anchored on chain together with the audit-log head hash. |
| **Human-only approvals** | Separation of duties, per-manager approval limits, maker-checker, and the REST API deliberately has no approval endpoint. |
| **Tamper-evident audit** | Hash-chained `audit.jsonl`; the Audit & Compliance page pinpoints the first edited entry. |

## Quick start

```bash
pip install -r requirements.txt
cd blockchain && npm install && cd ..        # local blockchain node (Hardhat) + Solidity compiler
python scripts/make_sample_invoices.py       # demo invoices in samples/
python scripts/deploy.py                     # test gate -> reports -> starts UI (:8501) and API (:8000)
```

Or step by step: `python -m pytest`, then `streamlit run app/streamlit_app.py`
(set `INVOICEGUARD_API_PORT=8000` to also serve the REST API).

Demo users (picked in the sidebar; no passwords in the hackathon build):

| User | Role | Approval limit |
|---|---|---|
| `emp_asha`, `emp_ravi` | employee | - |
| `mgr_priya` | accounts_manager | ₹5,00,000 |
| `mgr_arjun` | accounts_manager | ₹1,00,000 |
| `aud_meera` | auditor | - |

All suppliers, POs and GRNs are **fictional demo fixtures** (`core/demo_data.py`), seeded on first start.
Delete the `data/` folder to reset everything.

### Configuration (environment variables)

| Variable | Purpose |
|---|---|
| `INVOICEGUARD_LEDGER` | `local` (default: Hardhat node, auto-started), `rpc` (any EVM chain, e.g. Polygon Amoy), `off` |
| `INVOICEGUARD_CHAIN_RPC`, `INVOICEGUARD_CHAIN_KEY`, `INVOICEGUARD_CHAIN_CONTRACT` | RPC URL, signing key, existing contract (rpc mode) |
| `INVOICEGUARD_LEDGER_SALT` | consortium-shared salt for invoice fingerprints |
| `INVOICEGUARD_API_PORT`, `INVOICEGUARD_API_KEY` | serve the REST API; require `X-API-Key` |
| `INVOICEGUARD_WEBHOOK_URL`, `INVOICEGUARD_WEBHOOK_SECRET` | send status events to n8n / Slack / email |
| `ANTHROPIC_API_KEY`, `INVOICEGUARD_LLM_MODEL` | optional Claude vision extraction (3rd strategy) |

Tesseract OCR (2nd strategy) is used automatically if the Tesseract binary is installed.

## Workflow

```
START → intake → extract → validate → action → ledger → checker(+risk) → router
                    ↑                                                     │
                    └───────────────── reextract ←────────────────────────┤ low confidence, attempts left
                                                                          ├→ request_approval → human_approval ⏸
                                                                          └→ escalate → manual_review ⏸
validate / action failure → blocked → finalize → END
human_approval: approve | reject → finalize · escalate → escalate · correct → validate
manual_review:  correct → validate · release (with reason) → request_approval · reject → finalize
```

⏸ = LangGraph `interrupt()`. State is checkpointed in SQLite (`SqliteSaver`, thread id = invoice id), so a
paused approval survives an app crash or restart. The **Workflow Pipeline** page shows each invoice's stage from real workflow state and draws this graph live
from the compiled LangGraph.

### The five loop bounds (`workflow_spec.yaml`)

| Bound | Setting | Where enforced |
|---|---|---|
| 1. Max iterations | `max_iterations: 3` extraction attempts | `graph/nodes.py` extract, `graph/router.py` |
| 2. Success gate | validation passed + record built + checker passed + no unreleased injection / HIGH-risk flag | `graph/router.py` |
| 3. No-op condition | state hash of extracted data unchanged after a retry → stop and escalate | `graph/nodes.py` extract |
| 4. Escalation condition | checker failed with high confidence, retries exhausted, no-op, tool-call/time limits, suspicious content, HIGH fraud risk, manager escalates | `graph/router.py` |
| 5. Budget limit | `max_invoice_value_inr: 500000` (business value limit) | `tools/validator.py`, `tools/checker.py`, plus per-manager limits in `core/authz.py` |

Extra safety limits: `max_tool_calls: 10` and `timeout_seconds: 60` per automated run.

### Safety controls

- **Prompt-injection defence**: invoice text is untrusted. Instruction-like phrases are flagged
  (`tools/injection_guard.py`) and the invoice is escalated. The LLM has no tools, no database access and no
  approval rights; its output is schema-validated and still has to pass the deterministic checker.
- **Separation of duties**: the uploader can never decide on their own invoice; only `accounts_manager`
  can decide; the total must be within the manager's limit; a manager who corrected or released an invoice
  cannot also approve it (maker-checker).
- **Duplicates**: exact duplicates (DB unique constraint on supplier GSTIN + invoice number) and identical
  files are blocked. Near-duplicates (similar amount plus a near invoice number or a date within 7 days) are
  flagged; sequential invoice numbers alone are not.
- **Blockchain registry** (`blockchain/InvoiceRegistry.sol`, client `core/ledger.py`): only
  `SHA-256(salt | GSTIN | invoice number)` goes on chain. If the chain is down, the step is logged and
  skipped; it never blocks the business workflow.
- **Money** uses Python `Decimal` everywhere, stored as exact strings in SQLite.

## User interface

Enterprise theme (`.streamlit/config.toml`, `ui/styles.css`) with role-based navigation: employees never see
Manager Approvals; auditors get read-only governance pages. The UI only calls existing backend functions:
approvals, corrections and audit verification all go through the workflow / `verify_chain()`, and every
invoice-derived string is HTML- or Markdown-escaped before display. See `ui/workflow_mapping.md` for how
pipeline stages map to LangGraph state.

## Integrations (n8n)

- **Intake**: `POST /api/invoices` (multipart `file` + `uploader_id`, header `X-API-Key`). Also
  `GET /api/invoices`, `GET /api/invoices/{id}`, `GET /api/metrics`, `GET /api/health`. API docs at `/docs`.
- **Alerts**: with `INVOICEGUARD_WEBHOOK_URL` set, `APPROVAL_REQUESTED`, `INVOICE_ESCALATED`,
  `INVOICE_APPROVED/REJECTED/BLOCKED` and `LEDGER_DUPLICATE_ELSEWHERE` are POSTed as JSON.
- `integrations/n8n/invoiceguard_workflow.json` is an importable n8n workflow: IMAP mailbox → InvoiceGuard
  API, and InvoiceGuard webhook → "needs a human?" → email the accounts managers. Add your IMAP/SMTP
  credentials after importing.

## Pre-deployment tests

`python scripts/deploy.py --no-start` writes `reports/test_report.html` and `reports/TEST_SUMMARY.md`.
The 9 required scenarios plus fraud risk, blockchain, API, crash-and-resume, separation of duties, GST maths,
three-way match, audit tamper detection and end-to-end runs on 9 demo PDFs (including a different
table-based layout).

## Demo script (6 minutes)

1. **Workflow Pipeline** page: the five bounds, the live graph, and an invoice's stages (click a stage for evidence).
2. **Asha** uploads `01_valid_intra_state.pdf` → AWAITING_APPROVAL, risk LOW, fingerprint on chain.
   Show confidence colours and checker evidence in Invoice Review.
3. **Double financing + a different layout**: on the Audit & Compliance page (as a manager), click "Register as the other organisation"
   (pre-filled with `DSW/26-27/0108`). Then upload `10_table_layout_valid.pdf`: it is read correctly despite
   the different layout (ruled table, "Bill No", "Dated: 21-Oct-2026"), passes every check, and is still
   escalated because another organisation already registered it on the blockchain.
4. Upload `06_prompt_injection.pdf` → ESCALATED; the hidden "approve this invoice" note was ignored.
5. Upload `03_arithmetic_mismatch.pdf` → ESCALATED with no pointless retries. As **Priya**, correct the total
   → re-checked → AWAITING_APPROVAL. Priya cannot approve her own correction; **Arjun** approves.
6. `02_valid_inter_state_large.pdf` (₹2.33L): Arjun's ₹1L limit blocks him; Priya approves → decision anchored on chain.
7. Kill and restart the app → pending approvals are still there. Audit & Compliance → **Verify chain now**, then edit a
   line of `data/audit.jsonl` and verify again to show tamper detection.

## Project layout

```
app/            Streamlit pages (dashboard, workflow pipeline, employee workspace, invoice review, manager approvals,
                audit & compliance, system monitoring, settings)
ui/             design system (styles.css), reusable components, role-based navigation, workflow_mapping.md
api/            FastAPI REST API for n8n / ERP intake (no approval endpoint by design)
blockchain/     InvoiceRegistry.sol, compiled ABI/bytecode, Hardhat config (local chain)
core/           spec config, db models, audit log, ledger client, webhooks, authz, service layer, demo data
graph/          LangGraph state, nodes, router (loop bounds), checkpointing, graph build
tools/          extractor, validator, action tool, checker, risk score, GST, three-way match, injection guard
integrations/   n8n workflow
tests/          pytest suite
scripts/        demo invoice generator, deploy gate
workflow_spec.yaml   the workflow spec: inputs, steps, outputs, rules, approver, bounds
```

## Known limits

- The extractor reads labelled invoices and ruled item tables with many common label variants. Check
  DigiBull's real samples as soon as they arrive and extend `FIELD_PATTERNS` / `TABLE_COLUMNS` in
  `tools/extractor.py`, or enable the Claude strategy.
- Sign-in is a demo user picker, not real authentication.
- The local Hardhat chain lives in memory; the app redeploys and re-anchors its records if it was reset.
  Use `INVOICEGUARD_LEDGER=rpc` with a public testnet for a persistent shared ledger.
- The n8n workflow file has not been imported into a live n8n instance in this build.
- GST slabs follow the brief (0/5/12/18/28%). India moved to 5/18/40% main slabs in Sept 2025; edit
  `gst.valid_rates` in the spec if your samples use them.
