"""REST API for integrations (n8n, email gateways, ERP). Intake and read-only status - by design there is
NO approval endpoint: approvals happen only through the authenticated human UI.

Run alongside the UI (same process, same ledger):  INVOICEGUARD_API_PORT=8000 streamlit run app/streamlit_app.py
Run on its own:                                     python -m api.server  (port 8000)
Set INVOICEGUARD_API_KEY to require an X-API-Key header.
"""
from __future__ import annotations

import json
import os
import threading

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, UploadFile

from core import service
from core.context import AppContext


def _plain(obj):
    return json.loads(json.dumps(obj, default=str))  # Decimals stay exact (as strings)


def create_app(ctx: AppContext) -> FastAPI:
    app = FastAPI(title="InvoiceGuard AI API", version="1.0",
                  description="Invoice intake and status. Approvals are human-only and not exposed here.")

    def require_key(x_api_key: str | None = Header(default=None)):
        expected = os.environ.get("INVOICEGUARD_API_KEY")
        if expected and x_api_key != expected:
            raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")

    @app.get("/api/health")
    def health():
        return {"status": "ok", "workflow": ctx.spec.workflow, "ledger": _plain(service.ledger_info(ctx)),
                "audit": ctx.audit.verify_chain()}

    @app.post("/api/invoices", dependencies=[Depends(require_key)])
    async def submit(file: UploadFile = File(...), uploader_id: str = Form(...)):
        try:
            inv = service.submit_invoice(ctx, uploader_id, file.filename or "upload", await file.read())
        except PermissionError as e:
            raise HTTPException(status_code=403, detail=str(e))
        except ValueError as e:
            raise HTTPException(status_code=422, detail=str(e))
        return _plain(_summary(inv))

    @app.get("/api/invoices", dependencies=[Depends(require_key)])
    def list_(status: str | None = None):
        return _plain([_summary(i) for i in service.list_invoices(ctx, statuses=(status,) if status else None)])

    @app.get("/api/invoices/{invoice_id}", dependencies=[Depends(require_key)])
    def get(invoice_id: str):
        try:
            return _plain(service.get_invoice(ctx, invoice_id))
        except KeyError:
            raise HTTPException(status_code=404, detail="Invoice not found")

    @app.get("/api/metrics", dependencies=[Depends(require_key)])
    def metrics():
        return _plain(service.metrics(ctx))

    return app


def _summary(inv: dict) -> dict:
    risk = (inv.get("checker") or {}).get("risk") or {}
    return {"id": inv["id"], "status": inv["status"], "invoice_number": inv["invoice_number"],
            "supplier": inv["supplier_name"], "grand_total": inv["grand_total"], "risk_score": risk.get("score"),
            "risk_level": risk.get("level"), "flags": inv["flags"], "escalation_reason": inv["escalation_reason"],
            "failure_reason": inv["failure_reason"], "ledger_status": (inv.get("ledger") or {}).get("status"),
            "awaiting": (inv.get("pending") or {}).get("type")}


def start_in_thread(ctx: AppContext, port: int) -> None:
    import uvicorn

    server = uvicorn.Server(uvicorn.Config(create_app(ctx), host="127.0.0.1", port=port, log_level="warning"))
    threading.Thread(target=server.run, name="invoiceguard-api", daemon=True).start()


if __name__ == "__main__":
    import sys
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import uvicorn

    from core.demo_data import seed_demo_data

    context = AppContext()
    seed_demo_data(context)
    uvicorn.run(create_app(context), host="127.0.0.1", port=int(os.environ.get("INVOICEGUARD_API_PORT", 8000)))
