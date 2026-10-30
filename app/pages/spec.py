import pandas as pd
import streamlit as st

from components.common import get_ctx, inr
from core import service

ctx = get_ctx()
spec = ctx.spec
st.title("Workflow Spec & Live Graph")
st.caption(f"`workflow_spec.yaml` - {spec.workflow} v{spec.version}, validated with Pydantic at startup. "
           f"Approver role: **{spec.approver}**.")

b = spec.bounds
st.subheader("The five loop bounds")
st.dataframe(pd.DataFrame([
    {"Bound": "1. Max iterations", "Setting": f"{b.max_iterations} extraction attempts",
     "What happens": "Escalate with MAX_ITERATIONS_REACHED"},
    {"Bound": "2. Success gate", "Setting": " AND ".join(spec.success_gate),
     "What happens": "Only then: pause for human approval"},
    {"Bound": "3. No-op condition", "Setting": b.no_op_rule,
     "What happens": "Identical re-extraction stops retries and escalates"},
    {"Bound": "4. Escalation condition", "Setting": "; ".join(spec.escalation_conditions),
     "What happens": "Manual review queue (correct / release / reject)"},
    {"Bound": "5. Budget limit", "Setting": f"Invoice value <= ₹{inr(b.max_invoice_value_inr)}",
     "What happens": "Blocked; plus per-manager approval limits"},
    {"Bound": "Extra safety", "Setting": f"{b.max_tool_calls} tool calls, {b.timeout_seconds}s per run",
     "What happens": "Escalate"},
]), hide_index=True, width="stretch")

st.subheader("Live LangGraph workflow")
st.caption("Drawn from the compiled graph that actually runs. Dashed = conditional route; "
           "human_approval and manual_review pause the graph (interrupt) until a person decides.")
g = ctx.graph.get_graph()
human = {"human_approval", "manual_review"}
dot = ["digraph G {", 'rankdir=TB; node [shape=box, style="rounded,filled", fillcolor="#eef4ff", fontname="Helvetica"];']
for node_id in g.nodes:
    if node_id in ("__start__", "__end__"):
        dot.append(f'"{node_id}" [label="{node_id.strip("_").upper()}", shape=oval, fillcolor="#e8e8e8"];')
    elif node_id in human:
        dot.append(f'"{node_id}" [fillcolor="#fff1d6", label="{node_id}\\n(human, interrupt)"];')
for e in g.edges:
    style = "dashed" if e.conditional else "solid"
    dot.append(f'"{e.source}" -> "{e.target}" [style={style}];')
for src, targets in {"human_approval": ["finalize", "escalate", "validate"],
                     "manual_review": ["validate", "request_approval", "finalize"]}.items():
    for t in targets:
        dot.append(f'"{src}" -> "{t}" [style=dotted, color="#b07000"];')
dot.append("}")
st.graphviz_chart("\n".join(dot), width="stretch")

c1, c2 = st.columns(2)
with c1:
    st.subheader("Rules")
    for r in spec.rules:
        st.markdown(f"- {r}")
with c2:
    st.subheader("Steps")
    for s in spec.steps:
        st.markdown(f"- **{s['id']}** ({s['kind']}) - {s['does']}")

st.subheader("Shared blockchain ledger")
info = service.ledger_info(ctx)
if info["enabled"]:
    st.success(f"Connected - mode `{info['mode']}`, chain id {info['chain_id']}, contract `{info['contract']}`, "
               f"{info['total_registered']} invoice fingerprints registered, block {info['block']}.")
else:
    st.warning(f"Ledger disabled: {info['reason']}")
