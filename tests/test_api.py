"""REST API (n8n intake) and outbound webhook notifications."""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from conftest import ROOT, FakeStrategy, result_from, submit, valid_intra_fields

pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from api.server import create_app  # noqa: E402


@pytest.fixture
def client(make_ctx, monkeypatch):
    monkeypatch.setenv("INVOICEGUARD_API_KEY", "test-key")
    ctx = make_ctx()  # real extraction strategies
    return TestClient(create_app(ctx)), ctx


def test_api_requires_key(client):
    c, _ = client
    assert c.get("/api/invoices").status_code == 401
    assert c.get("/api/health").json()["status"] == "ok"


def test_api_intake_runs_full_workflow(client):
    c, _ = client
    pdf = (ROOT / "samples" / "01_valid_intra_state.pdf").read_bytes()
    r = c.post("/api/invoices", headers={"X-API-Key": "test-key"}, data={"uploader_id": "emp_asha"},
               files={"file": ("inv.pdf", pdf, "application/pdf")})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "AWAITING_APPROVAL" and body["awaiting"] == "approval"
    assert body["grand_total"] == "8654.00"  # exact decimal string, not a float
    detail = c.get(f"/api/invoices/{body['id']}", headers={"X-API-Key": "test-key"}).json()
    assert detail["checker"]["passed"] is True


def test_api_rejects_bad_input(client):
    c, _ = client
    h = {"X-API-Key": "test-key"}
    assert c.post("/api/invoices", headers=h, data={"uploader_id": "emp_asha"},
                  files={"file": ("x.exe", b"MZ", "application/octet-stream")}).status_code == 422
    assert c.post("/api/invoices", headers=h, data={"uploader_id": "nobody"},
                  files={"file": ("x.pdf", b"%PDF", "application/pdf")}).status_code == 403
    assert c.get("/api/invoices/INV-NOPE", headers=h).status_code == 404


def test_api_has_no_approval_endpoint(client):
    c, _ = client
    paths = {route.path for route in c.app.routes}
    assert not any("decision" in p or "approve" in p for p in paths)


def test_webhook_notifications(make_ctx, monkeypatch):
    received = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            received.append(json.loads(self.rfile.read(int(self.headers["Content-Length"]))))
            self.send_response(200)
            self.end_headers()

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    monkeypatch.setenv("INVOICEGUARD_WEBHOOK_URL", f"http://127.0.0.1:{server.server_port}/hook")
    ctx = make_ctx({"fake": FakeStrategy(result_from(valid_intra_fields()))})
    inv = submit(ctx)
    deadline = time.time() + 5
    while not received and time.time() < deadline:
        time.sleep(0.05)
    server.shutdown()
    assert received and received[0]["event_type"] == "APPROVAL_REQUESTED"
    assert received[0]["invoice_id"] == inv["id"] and len(received[0]["audit_hash"]) == 64
