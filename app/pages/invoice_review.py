import pandas as pd
import streamlit as st

from components.common import confidence_badge, current_user, get_ctx, render_document, show_issues, status_badge
from core import service
from tools.models import LineItem

ctx = get_ctx()
user = current_user()
spec = ctx.spec
st.title("Invoice Review")

invoices = service.list_invoices(ctx)
if not invoices:
    st.info("No invoices yet.")
    st.stop()
ids = [i["id"] for i in invoices]
default = st.session_state.get("review_invoice_id")
labels = {i["id"]: f"{i['id']} · {i['status']} · {i['invoice_number'] or i['file_name']}" for i in invoices}
selected = st.selectbox("Invoice", ids, index=ids.index(default) if default in ids else 0, format_func=labels.get)
st.session_state["review_invoice_id"] = selected
inv = service.get_invoice(ctx, selected)
fields = inv["extracted"] or {}
conf = inv["field_confidence"] or {}

st.markdown(f"{status_badge(inv['status'])}  Extracted by `{inv['extraction_strategy'] or '-'}` · "
            f"overall confidence {confidence_badge(inv['confidence'], spec)}")

SCALAR = ("invoice_number", "invoice_date", "due_date", "po_number", "supplier_name", "supplier_gstin",
          "buyer_name", "buyer_gstin", "subtotal", "cgst", "sgst", "igst", "grand_total")
low = [f for f in SCALAR if fields.get(f) is not None and conf.get(f, 1) < spec.thresholds.green_confidence]

left, right = st.columns([1, 1])
with right:
    st.subheader("Extracted fields")
    for f in SCALAR:
        c1, c2, c3 = st.columns([2, 3, 1])
        c1.markdown(f"**{f.replace('_', ' ').title()}**")
        c2.markdown(f"`{fields.get(f)}`" if fields.get(f) is not None else ":gray[missing]")
        c3.markdown(confidence_badge(conf.get(f), spec) if fields.get(f) is not None else "")
    st.markdown(f"**Line items** {confidence_badge(conf.get('line_items'), spec)}")
    if fields.get("line_items"):
        st.dataframe(pd.DataFrame(fields["line_items"]), hide_index=True, width="stretch")
    if low:
        st.warning("Lower-confidence fields: " + ", ".join(low))
    show_issues(inv)

with left:
    highlight = st.multiselect("Highlight on document", [f for f in SCALAR if fields.get(f)], default=low[:3],
                               key=f"hl_{selected}")
    render_document(inv["file_path"], key=f"rev_{selected}", highlights=[fields[f] for f in highlight])

# ---------------------------------------------------------------- corrections
st.divider()
pending = inv["pending"] or {}
can_correct = "correct" in pending.get("allowed_actions", []) and user.role == spec.approver
st.subheader("Correct fields")
if not can_correct:
    st.caption("Corrections are available to accounts managers while an invoice is awaiting approval or escalated.")
else:
    st.caption("Every change is written to the audit log, then validation and the independent checker run again. "
               "A manager who corrects an invoice cannot also approve it.")
    with st.form(f"correct_{selected}"):
        cols = st.columns(3)
        edits = {}
        for n, f in enumerate(SCALAR):
            edits[f] = cols[n % 3].text_input(f.replace("_", " ").title(), value=fields.get(f) or "",
                                              key=f"c_{selected}_{f}")
        items_df = pd.DataFrame(fields.get("line_items") or [], columns=list(LineItem.model_fields))
        edited_items = st.data_editor(items_df.astype("string"), num_rows="fixed", hide_index=True,
                                      width="stretch", key=f"items_{selected}")
        if st.form_submit_button("Apply corrections and re-check", type="primary"):
            corrections = {f: v for f, v in edits.items() if (v or None) != fields.get(f)}
            old_items = fields.get("line_items") or []
            for i, row in edited_items.iterrows():
                for col in LineItem.model_fields:
                    new = None if pd.isna(row[col]) or row[col] == "" else str(row[col])
                    old = old_items[i].get(col) if i < len(old_items) else None
                    if new != (None if old is None else str(old)):
                        corrections[f"line_items.{i}.{col}"] = new
            if not corrections:
                st.info("No changes.")
            else:
                try:
                    out = service.decide(ctx, selected, user.id, "correct", corrections=corrections)
                    st.success(f"Re-checked: status is now {out['status']}")
                    st.rerun()
                except Exception as e:  # invalid numbers, permission errors
                    st.error(str(e))

with st.expander("Audit history for this invoice"):
    for e in ctx.audit.get_invoice_history(selected):
        st.markdown(f"`{e['seq']}` {e['timestamp'][:19]} **{e['event_type']}** by `{e['actor']}`")
        if e["event_data"]:
            st.caption(str(e["event_data"])[:400])
