"""Append-only, SHA-256 hash-chained audit log (audit.jsonl), mirrored into the audit_events table."""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import select

from core.db import AuditEvent

GENESIS_HASH = "0" * 64
_HASHED_FIELDS = ("event_id", "seq", "invoice_id", "event_type", "timestamp", "actor", "event_data", "previous_hash")


def _canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)


def compute_hash(event: dict) -> str:
    payload = {k: event[k] for k in _HASHED_FIELDS}
    return hashlib.sha256(_canonical(payload).encode("utf-8")).hexdigest()


class AuditLog:
    def __init__(self, path: Path, session_factory):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.touch(exist_ok=True)
        self._session_factory = session_factory
        self._lock = threading.Lock()
        self.listeners: list = []  # callables(event) run after each append, e.g. webhook notifications

    def head_hash(self) -> str:
        return self._tail()[1]

    def _read_all(self) -> list[dict]:
        events = []
        with open(self.path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    events.append(json.loads(line))
        return events

    def _tail(self) -> tuple[int, str]:
        events = self._read_all()
        if not events:
            return 0, GENESIS_HASH
        return events[-1]["seq"], events[-1]["current_hash"]

    @contextmanager
    def _file_lock(self):
        """Cross-process lock, so a separate API process and the UI never interleave appends."""
        lock = self.path.with_name(self.path.name + ".lock")
        deadline = time.time() + 10
        while True:
            try:
                fd = os.open(lock, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                break
            except FileExistsError:
                try:
                    if time.time() - lock.stat().st_mtime > 30:  # stale lock from a crashed process
                        lock.unlink()
                except FileNotFoundError:
                    pass
                if time.time() > deadline:
                    raise TimeoutError("Could not lock the audit log")
                time.sleep(0.02)
        try:
            yield
        finally:
            os.close(fd)
            lock.unlink(missing_ok=True)

    def append_event(self, invoice_id: str | None, event_type: str, actor: str, event_data: dict | None = None) -> dict:
        data = json.loads(_canonical(event_data or {}))  # normalise Decimals etc. so hashes are reproducible
        with self._lock, self._file_lock():
            last_seq, prev_hash = self._tail()
            event = {
                "event_id": uuid.uuid4().hex[:16],
                "seq": last_seq + 1,
                "invoice_id": invoice_id,
                "event_type": event_type,
                "timestamp": datetime.now(timezone.utc).isoformat(timespec="milliseconds"),
                "actor": actor,
                "event_data": data,
                "previous_hash": prev_hash,
            }
            event["current_hash"] = compute_hash(event)
            with open(self.path, "a", encoding="utf-8") as f:
                f.write(_canonical(event) + "\n")
                f.flush()
                os.fsync(f.fileno())
            with self._session_factory() as s:
                s.add(AuditEvent(**{**event, "event_data": _canonical(data)}))
                s.commit()
        for listener in self.listeners:
            try:
                listener(event)
            except Exception:  # a notification problem must never break the audit trail
                pass
        return event

    def verify_chain(self) -> dict:
        """Recompute every hash. Reports the first broken entry if the file was tampered with."""
        prev = GENESIS_HASH
        try:
            events = self._read_all()
        except json.JSONDecodeError as e:
            return {"intact": False, "count": None, "first_broken_seq": None, "reason": f"Unreadable line: {e}"}
        for i, ev in enumerate(events):
            if ev.get("previous_hash") != prev:
                return {"intact": False, "count": len(events), "first_broken_seq": ev.get("seq", i + 1),
                        "event_id": ev.get("event_id"), "reason": "previous_hash does not match the prior entry"}
            if compute_hash(ev) != ev.get("current_hash"):
                return {"intact": False, "count": len(events), "first_broken_seq": ev.get("seq", i + 1),
                        "event_id": ev.get("event_id"), "reason": "entry content was modified (hash mismatch)"}
            prev = ev["current_hash"]
        return {"intact": True, "count": len(events), "first_broken_seq": None, "head_hash": prev}

    def get_invoice_history(self, invoice_id: str) -> list[dict]:
        return [e for e in self._read_all() if e.get("invoice_id") == invoice_id]

    def get_recent_events(self, limit: int = 50) -> list[dict]:
        with self._session_factory() as s:
            rows = s.scalars(select(AuditEvent).order_by(AuditEvent.seq.desc()).limit(limit)).all()
            return [{"seq": r.seq, "event_id": r.event_id, "invoice_id": r.invoice_id, "event_type": r.event_type,
                     "timestamp": r.timestamp, "actor": r.actor, "event_data": json.loads(r.event_data)} for r in rows]
