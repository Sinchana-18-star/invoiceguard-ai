"""Assemble the InvoiceGuard StateGraph.

START -> intake -> extract -> validate -> action -> ledger -> checker -> router
  router -> request_approval -> human_approval (interrupt) -> finalize | escalate | validate (after correction)
  router -> reextract -> extract                      (extraction-only retry, bounded)
  router -> escalate -> manual_review (interrupt) -> validate | request_approval | finalize
  validate/action failure -> blocked -> finalize -> END
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, START, StateGraph

from graph import router as r
from graph.nodes import build_nodes
from graph.state import InvoiceState

if TYPE_CHECKING:
    from core.context import AppContext


def build_graph(ctx: "AppContext"):
    nodes = build_nodes(ctx)
    g = StateGraph(InvoiceState)
    for name, fn in nodes.items():
        g.add_node(name, fn)

    g.add_edge(START, "intake")
    g.add_edge("intake", "extract")
    g.add_conditional_edges("extract", r.after_extract, {"validate": "validate", "escalate": "escalate"})
    g.add_conditional_edges("validate", r.after_validate, {"action": "action", "blocked": "blocked"})
    g.add_conditional_edges("action", r.after_action, {"ledger": "ledger", "blocked": "blocked"})
    g.add_edge("ledger", "checker")
    g.add_edge("checker", "router")
    g.add_conditional_edges("router", r.after_router, {"request_approval": "request_approval",
                                                       "reextract": "reextract", "escalate": "escalate"})
    g.add_edge("reextract", "extract")
    g.add_edge("request_approval", "human_approval")
    g.add_edge("escalate", "manual_review")
    g.add_edge("blocked", "finalize")
    g.add_edge("finalize", END)
    # human_approval and manual_review route themselves with Command(goto=...)
    return g.compile(checkpointer=ctx.checkpointer)
