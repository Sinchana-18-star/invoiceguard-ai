"""Persistent LangGraph checkpoints in SQLite, so paused approvals survive a crash or restart."""
from __future__ import annotations

import sqlite3
from pathlib import Path

from langgraph.checkpoint.sqlite import SqliteSaver


def open_checkpointer(path: Path) -> tuple[SqliteSaver, sqlite3.Connection]:
    conn = sqlite3.connect(str(path), check_same_thread=False)
    saver = SqliteSaver(conn)
    saver.setup()
    return saver, conn


def thread_config(invoice_id: str) -> dict:
    # invoice_id is the workflow thread id
    return {"configurable": {"thread_id": invoice_id}, "recursion_limit": 100}
