"""Outbound webhook notifications (e.g. to an n8n Webhook node -> Slack / email / Teams).

Set INVOICEGUARD_WEBHOOK_URL to enable. Only status-changing events are sent, in a background thread
with a short timeout, so a slow or broken receiver never delays the workflow.
"""
from __future__ import annotations

import json
import os
import threading
import urllib.request

NOTIFY_EVENTS = {"APPROVAL_REQUESTED", "INVOICE_ESCALATED", "INVOICE_APPROVED", "INVOICE_REJECTED",
                 "INVOICE_BLOCKED", "LEDGER_DUPLICATE_ELSEWHERE"}


class WebhookNotifier:
    def __init__(self, url: str, secret: str | None = None):
        self.url, self.secret = url, secret
        self.sent: list[dict] = []  # last payloads, for the UI and tests

    @classmethod
    def from_env(cls) -> "WebhookNotifier | None":
        url = os.environ.get("INVOICEGUARD_WEBHOOK_URL")
        return cls(url, os.environ.get("INVOICEGUARD_WEBHOOK_SECRET")) if url else None

    def on_event(self, event: dict) -> None:
        if event["event_type"] not in NOTIFY_EVENTS:
            return
        payload = {"source": "invoiceguard", "event_type": event["event_type"], "invoice_id": event["invoice_id"],
                   "actor": event["actor"], "timestamp": event["timestamp"], "data": event["event_data"],
                   "audit_hash": event["current_hash"]}
        self.sent = (self.sent + [payload])[-50:]
        threading.Thread(target=self._post, args=(payload,), daemon=True).start()

    def _post(self, payload: dict) -> None:
        headers = {"Content-Type": "application/json"}
        if self.secret:
            headers["X-InvoiceGuard-Secret"] = self.secret
        req = urllib.request.Request(self.url, data=json.dumps(payload, default=str).encode(), headers=headers,
                                     method="POST")
        try:
            urllib.request.urlopen(req, timeout=5).close()
        except Exception:
            pass  # delivery is best-effort; the audit log remains the record of truth
