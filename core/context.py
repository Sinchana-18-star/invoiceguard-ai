"""Application context: paths, database, audit log, ledger, notifier, checkpointer and the workflow graph."""
from __future__ import annotations

import json
import os
from pathlib import Path

from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import sessionmaker

from core.audit import AuditLog
from core.config import ROOT, load_spec
from core.db import Base, Invoice
from core.notify import WebhookNotifier
from graph.build import build_graph
from graph.checkpoint import open_checkpointer
from tools.extractor import DEFAULT_STRATEGIES, Strategy


def add_missing_columns(engine) -> None:
    """Tiny forward-only migration: add nullable columns that exist in the models but not in the DB file."""
    insp = inspect(engine)
    with engine.begin() as conn:
        for table in Base.metadata.sorted_tables:
            if not insp.has_table(table.name):
                continue
            have = {c["name"] for c in insp.get_columns(table.name)}
            for col in table.columns:
                if col.name not in have and col.nullable:
                    conn.execute(text(f'ALTER TABLE {table.name} ADD COLUMN "{col.name}" '
                                      f'{col.type.compile(engine.dialect)}'))


class AppContext:
    def __init__(self, data_dir: Path | str | None = None, spec_path: Path | str | None = None,
                 strategies: dict[str, Strategy] | None = None, strategy_order: list[str] | None = None):
        self.spec = load_spec(spec_path)
        self.data_dir = Path(data_dir or os.environ.get("INVOICEGUARD_DATA_DIR") or ROOT / "data")
        self.uploads_dir = self.data_dir / "uploads"
        self.snapshots_dir = self.data_dir / "snapshots"
        for d in (self.data_dir, self.uploads_dir, self.snapshots_dir):
            d.mkdir(parents=True, exist_ok=True)

        self.engine = create_engine(f"sqlite:///{self.data_dir / 'invoiceguard.db'}",
                                    connect_args={"check_same_thread": False})
        Base.metadata.create_all(self.engine)
        add_missing_columns(self.engine)
        self.Session = sessionmaker(self.engine, expire_on_commit=False)
        self.audit = AuditLog(self.data_dir / "audit.jsonl", self.Session)
        self.notifier = WebhookNotifier.from_env()
        if self.notifier:
            self.audit.listeners.append(self.notifier.on_event)

        self.ledger, self.ledger_error = None, None
        try:
            from core.ledger import Ledger
            self.ledger = Ledger.from_env(self.data_dir)
            if self.ledger and self.ledger.fresh_contract and self.ledger.mode == "local":
                self._reanchor_local_ledger()
        except Exception as e:  # missing web3, chain down, bad config: run without the ledger
            self.ledger_error = f"{e.__class__.__name__}: {e}"

        self.strategies = strategies or dict(DEFAULT_STRATEGIES)
        self.strategy_order = strategy_order or [s for s in self.spec.extraction_strategies if s in self.strategies]

        self.checkpointer, self._ckpt_conn = open_checkpointer(self.data_dir / "checkpoints.sqlite")
        self.graph = build_graph(self)

    def _reanchor_local_ledger(self) -> None:
        """A reset dev chain is empty: re-register this organisation's records from the database."""
        with self.Session() as s:
            rows = s.scalars(select(Invoice).where(Invoice.ledger_json.is_not(None))).all()
        for inv in rows:
            data = json.loads(inv.ledger_json)
            if data.get("status") not in ("REGISTERED", "ALREADY_OURS"):
                continue
            key = bytes.fromhex(data["invoice_key"])
            self.ledger._send(self.ledger.contract.functions.registerInvoice(key))
            if data.get("decision_hash"):
                self.ledger.record_decision(data["invoice_key"], data.get("decision") == "APPROVED",
                                            bytes.fromhex(data["decision_hash"]))

    def write_snapshot(self, state: dict, node: str) -> None:
        """JSON snapshot of the latest workflow state for each invoice (human-readable, for audits/demo)."""
        path = self.snapshots_dir / f"{state['invoice_id']}.json"
        payload = {"last_node": node, "state": {k: v for k, v in state.items() if k != "raw_text"}}
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
        tmp.replace(path)

    def close(self) -> None:
        self._ckpt_conn.close()
        self.engine.dispose()
