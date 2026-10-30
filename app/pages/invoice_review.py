import pandas as pd
import streamlit as st

from core.db import Status
from tools.models import LineItem
from ui import data
from ui.access import require
from ui.components.audit_timeline import timeline
from ui.components.badges import confidence_badge, risk_badge, status_badge, verification, verification_badge
from ui.components.fields import LABELS, SECTIONS, field_table, uncertain_fields
from ui.components.preview import document_preview
from ui.components.shell import page_header
from ui.components.states import empty_state, error_state, notice
from ui.format import esc, md_safe, money
from ui.runtime import get_ctx

user = page_header("review", "Operations", "Original document side by side with what was extracted and verified.")
require(user, "review")
spec = get_ctx().spec

invoices = data.invoices_for(user)
if not invoices:
    empty_state("No invoices to review yet", "Invoices appear here once they are uploaded.")
    st.stop()

ids = [i["id"] for i in invoices]
labels = {i["id"]: f"{i['invoice_number'] or i['file_name']}  ·  {i['id']}" for i in invoices}
default = st.session_state.get("review_invoice_id")
selected = st.selectbox("Invoice", ids, index=ids.index(default) if default in ids else 0, format_func=labels.get)
st.session_state["review_invoice_id"] = selected

try:
    inv = data.invoice(selected)
except Exception as e:  # noqa: BLE001
    error_state("load this invoice", e)
    st.stop()

fields = inv["extracted"] or {}
conf = inv["field_confidence"] or {}
pending = inv["pending"] or {}

st.html(f"<div style='display:flex;gap:8px;flex-wrap:wrap;align-items:center'>{status_badge(inv['status'])}"
        f"{verification_badge(inv)}{risk_badge(inv)}<span class='ig-subtitle'>Extracted by "
        f"<b>{esc(inv['extraction_strategy'] or '-')}</b> · overall confidence "
        f"{confidence_badge(inv['confidence'], spec)}</span></div>")
if verification(inv)[0] == "Verification pending":
    notice("info", "Verification pending", body="The workflow is still validating and checking this invoice. "
                                                "It is not verified yet.")

uncertain = uncertain_fields(fields, conf, spec)
left, right = st.columns([1, 1], gap="large")

with left:
    st.html('<div class="ig-section-title">Original document</div>')
    keys_by_label = {LABELS[k]: k for k in LABELS if fields.get(k)}
    highlight = st.multiselect("Highlight on document", list(keys_by_label),
                               default=[u for u in uncertain if u in keys_by_label][:3], key=f"hl_{selected}")
    document_preview(inv, key=f"rev_{selected}", highlights=[fields[keys_by_label[h]] for h in highlight])

with right:
    if not fields:
        empty_state("Nothing was extracted", inv["escalation_reason"] or inv["failure_reason"] or
                    "No extraction strategy could read this document.", icon=":material/scan_delete:")
    for title, keys in SECTIONS.items():
        st.html(f'<div class="ig-section-title">{esc(title)}</div>')
        field_table(fields, conf, keys, spec)
        if title == "Invoice details":
            st.html(f'<div class="ig-section-title">Line items '
                    f'{confidence_badge(conf.get("line_items"), spec) if fields.get("line_items") else ""}</div>')
            items = fields.get("line_items") or []
            if items:
                st.dataframe(pd.DataFrame([{
                    "Description": li.get("description") or "-", "Qty": li.get("quantity") or "-",
                    "Unit price": money(li.get("unit_price")), "GST %": li.get("gst_rate") or "-",
                    "Taxable value": money(li.get("taxable_value"))} for li in items]),
                    hide_index=True, width="stretch")
            else:
                st.caption("No line items extracted.")

    st.html('<div class="ig-section-title">Extraction confidence</div>')
    t = spec.thresholds
    st.caption(f"Green ≥ {t.green_confidence:.2f} · Amber ≥ {t.amber_confidence:.2f} · Red below. "
               f"Low-confidence extraction (< {t.low_confidence:.2f}) is retried with the next strategy "
               f"before anything is escalated.")
    if uncertain:
        notice("warning", "Fields to double-check", uncertain)
    elif fields:
        notice("success", "All extracted fields are high confidence")

# ---------------------------------------------------------------- verification results
st.html('<div class="ig-section-title">Validation and independent checker</div>')
v, c = inv.get("validation") or {}, inv.get("checker") or {}
col1, col2 = st.columns(2, gap="large")
with col1:
    if v.get("errors"):
        notice("danger", "Validation errors (invoice blocked)", [f"{e['code']}: {e['message']}" for e in v["errors"]])
    elif v:
        notice("success", "Validation passed")
    if v.get("warnings"):
        notice("warning", "Warnings for the reviewer", [f"{w['code']}: {w['message']}" for w in v["warnings"]])
    if inv["failure_reason"] and not v.get("errors"):
        notice("danger", "Blocked", body=inv["failure_reason"])
with col2:
    if c:
        notice("success" if c.get("passed") else "danger",
               "Independent checker passed" if c.get("passed") else "Independent checker failed",
               c.get("reasons") or None)
        with st.expander("Checker evidence and calculated values"):
            for e in c.get("evidence", []):
                st.text(f"• {e}")
            if c.get("calculated_values"):
                st.dataframe(pd.DataFrame([{"Value": k, "Calculated": money(val)}
                                           for k, val in c["calculated_values"].items()]), hide_index=True)
    if inv["status"] == Status.ESCALATED and inv["escalation_reason"]:
        notice("warning", "Escalated for manual review", body=inv["escalation_reason"])

# ---------------------------------------------------------------- authorised correction
st.html('<div class="ig-section-title">Field correction</div>')
can_role = user["role"] == spec.approver
can_now = "correct" in pending.get("allowed_actions", [])
if not can_role:
    st.caption("Only accounts managers can correct extracted fields.")
elif not can_now:
    st.caption("Corrections are possible while an invoice is awaiting approval or escalated for review.")
elif user["id"] == inv["uploader_id"]:
    st.caption("You uploaded this invoice, so separation of duties prevents you from correcting it.")
else:
    st.caption("Every change is written to the audit log. The workflow then re-runs validation and the "
               "independent checker. A manager who corrects an invoice cannot also approve it.")
    scalar = list(LABELS)
    with st.form(f"correct_{selected}"):
        cols = st.columns(3)
        edits = {k: cols[n % 3].text_input(LABELS[k], value=fields.get(k) or "", key=f"c_{selected}_{k}")
                 for n, k in enumerate(scalar)}
        items_df = pd.DataFrame(fields.get("line_items") or [], columns=list(LineItem.model_fields))
        edited = st.data_editor(items_df.astype("string"), num_rows="fixed", hide_index=True, width="stretch",
                                key=f"items_{selected}")
        submitted = st.form_submit_button("Apply corrections and re-verify", type="primary")
    if submitted:
        corrections = {k: v for k, v in edits.items() if (v or None) != fields.get(k)}
        old_items = fields.get("line_items") or []
        for i, row in edited.iterrows():
            for col in LineItem.model_fields:
                new = None if pd.isna(row[col]) or row[col] == "" else str(row[col])
                old = old_items[i].get(col) if i < len(old_items) else None
                if new != (None if old is None else str(old)):
                    corrections[f"line_items.{i}.{col}"] = new
        if not corrections:
            st.info("No changes to apply.")
        else:
            with st.status("Verification pending: re-running validation and the independent checker...",
                           expanded=True) as box:
                try:
                    out = data.decide(selected, user["id"], "correct", corrections=corrections)
                    label, kind = verification(out)
                    box.update(label=f"Re-verification finished: {label} · status {out['status']}",
                               state="complete" if kind == "success" else "error")
                    st.write(f"{len(corrections)} change(s) recorded in the audit log.")
                except Exception as e:  # noqa: BLE001 - show the backend's own message
                    box.update(label="Correction refused", state="error")
                    st.error(md_safe(e))
            st.button("Show updated invoice", on_click=lambda: None)

with st.expander("Audit history for this invoice"):
    timeline(data.history(selected))
