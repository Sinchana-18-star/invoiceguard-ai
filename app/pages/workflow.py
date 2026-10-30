import pandas as pd
import streamlit as st

from ui import data
from ui.access import require
from ui.components.badges import status_badge
from ui.components.shell import page_header
from ui.components.states import empty_state, error_state, notice
from ui.components.workflow import STATE_STYLE, build_stages, pipeline_svg
from ui.format import esc, money, render_svg_markup
from ui.runtime import get_ctx

user = page_header("workflow", "Overview", "Where each invoice is in the verification pipeline, from real "
                                           "workflow state.")
require(user, "workflow")
ctx = get_ctx()
spec = ctx.spec

invoices = data.invoices_for(user)
if not invoices:
    empty_state("No invoices in the pipeline", "Upload an invoice to see it move through the workflow.")
else:
    ids = [i["id"] for i in invoices]
    labels = {i["id"]: f"{i['invoice_number'] or i['file_name']}  ·  {i['id']}" for i in invoices}
    default = st.session_state.get("review_invoice_id")
    selected = st.selectbox("Invoice", ids, index=ids.index(default) if default in ids else 0,
                            format_func=labels.get)
    st.session_state["review_invoice_id"] = selected
    try:
        inv, state, hist = data.invoice(selected), data.workflow_state(selected), data.history(selected)
        stages = build_stages(inv, state, hist, spec)
    except Exception as e:  # noqa: BLE001
        error_state("load the workflow state", e)
        st.stop()

    focus = next((s["key"] for s in stages if s["state"] in ("active", "failed", "escalated")), stages[-1]["key"])
    names = {s["key"]: f"{n + 1}. {s['name']}" for n, s in enumerate(stages)}
    pick = st.segmented_control("Stage", [s["key"] for s in stages], format_func=names.get, default=focus,
                                key=f"stage_{selected}", label_visibility="collapsed") or focus
    render_svg_markup(pipeline_svg(stages, selected=pick))
    st.caption("Select a stage above to see its evidence. Colours: green completed · blue active · amber "
               "escalated · red failed · dashed pending.")

    stage = next(s for s in stages if s["key"] == pick)
    with st.container(border=True):
        label = STATE_STYLE[stage["state"]][3]
        kind = {"completed": "success", "active": "info", "pending": "neutral", "failed": "danger",
                "escalated": "warning"}[stage["state"]]
        st.html(f"<div style='display:flex;gap:10px;align-items:center'><span class='ig-title' "
                f"style='font-size:17px'>{esc(stage['name'])}</span><span class='ig-badge ig-b-{kind}'>"
                f"{esc(label)}</span>{status_badge(inv['status'])}</div>")
        latest = stage["latest_event"].replace("_", " ").title() if stage["latest_event"] else "None yet"
        st.html('<table class="ig-fields">'
                f'<tr><td class="ig-label">Latest event</td><td class="ig-value">{esc(latest)}</td></tr>'
                f'<tr><td class="ig-label">Timestamp</td><td class="ig-value">{esc(stage["timestamp"] or "-")}</td></tr>'
                f'<tr><td class="ig-label">Retries</td><td class="ig-value">{esc(stage.get("retry", "Not applicable"))}</td></tr>'
                "</table>")
        if stage["error"]:
            notice("danger" if stage["state"] == "failed" else "warning",
                   "Escalation reason" if stage["state"] == "escalated" else "Error", body=stage["error"])
        if stage["evidence"]:
            notice("info", "Evidence", stage["evidence"])
        elif not stage["error"]:
            st.caption("No evidence recorded for this stage yet.")

with st.expander("How the workflow is wired: spec, loop bounds and the live LangGraph graph"):
    b = spec.bounds
    st.dataframe(pd.DataFrame([
        {"Bound": "1. Max iterations", "Setting": f"{b.max_iterations} extraction attempts"},
        {"Bound": "2. Success gate", "Setting": " AND ".join(spec.success_gate)},
        {"Bound": "3. No-op condition", "Setting": b.no_op_rule},
        {"Bound": "4. Escalation condition", "Setting": "; ".join(spec.escalation_conditions)},
        {"Bound": "5. Budget limit", "Setting": f"Invoice value <= {money(b.max_invoice_value_inr)}"},
        {"Bound": "Extra safety", "Setting": f"{b.max_tool_calls} tool calls, {b.timeout_seconds}s per run"},
    ]), hide_index=True, width="stretch")
    g = ctx.graph.get_graph()
    dot = ["digraph G {", 'rankdir=LR; bgcolor="transparent"; node [shape=box, style="rounded,filled", '
                          'fillcolor="#EAF1FA", color="#3978C5", fontname="Helvetica", fontsize=10];']
    for node_id in g.nodes:
        if node_id in ("__start__", "__end__"):
            dot.append(f'"{node_id}" [label="{node_id.strip("_").upper()}", shape=oval, fillcolor="#EEF2F7", color="#718096"];')
        elif node_id in ("human_approval", "manual_review"):
            dot.append(f'"{node_id}" [fillcolor="#FBF3E4", color="#D99A32", label="{node_id}\\n(human)"];')
    for e in g.edges:
        dot.append(f'"{e.source}" -> "{e.target}" [style={"dashed" if e.conditional else "solid"}, color="#718096"];')
    for src, targets in {"human_approval": ["finalize", "escalate", "validate"],
                         "manual_review": ["validate", "request_approval", "finalize"]}.items():
        for t in targets:
            dot.append(f'"{src}" -> "{t}" [style=dotted, color="#D99A32"];')
    dot.append("}")
    st.graphviz_chart("\n".join(dot), width="stretch")
    st.caption("Drawn from the compiled graph that runs. Dashed = conditional route, dotted = human decision.")
