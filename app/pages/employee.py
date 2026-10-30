import pandas as pd
import streamlit as st

from core.config import ROOT
from ui import data
from ui.access import PAGES, require
from ui.components.badges import STATUS_STYLE, status_badge, status_label, verification, verification_badge
from ui.components.shell import page_header
from ui.components.states import empty_state, notice
from ui.format import esc, md_safe, money

user = page_header("employee", "Operations", "Submit supplier invoices. They are verified automatically and sent "
                                             "to an accounts manager. Nothing is ever paid automatically.")
require(user, "employee")
SAMPLES = ROOT / "samples"


def run_submission(name: str, payload: bytes) -> None:
    with st.status(f"Processing {md_safe(name)}...", expanded=True) as box:
        st.write("Uploading and fingerprinting the file")
        st.write("Running extraction, validation, ledger registration and the independent checker")
        try:
            out = data.submit(user["id"], name, payload)
        except (ValueError, PermissionError) as e:
            box.update(label=f"Upload refused: {md_safe(e)}", state="error")
            return
        label, kind = verification(out)
        box.update(label=f"{md_safe(name)}: {status_label(out['status'])} · {label}",
                   state="error" if out["status"] in ("BLOCKED",) else "complete")
    st.session_state["_last_submission"] = out["id"]


up, side = st.columns([3, 2], gap="large")
with up:
    st.html('<div class="ig-section-title">Upload an invoice</div>')
    file = st.file_uploader("Drag and drop a PDF, PNG, JPG or JPEG (one invoice per file)",
                            type=["pdf", "png", "jpg", "jpeg"])
    if file is not None:
        st.html(f"<div class='ig-subtitle'>Selected: <b>{esc(file.name)}</b> · "
                f"<span class='ig-num'>{file.size / 1024:,.1f} KB</span></div>")
    if st.button("Submit for verification", type="primary", disabled=file is None, icon=":material/send:"):
        run_submission(file.name, file.getvalue())
with side:
    st.html('<div class="ig-section-title">Demo invoices (fictional)</div>')
    samples = sorted(p.name for p in SAMPLES.glob("*") if p.suffix.lower() in {".pdf", ".png", ".jpg", ".jpeg"})
    if samples:
        choice = st.selectbox("Sample", samples, label_visibility="collapsed")
        if st.button("Submit sample", icon=":material/science:"):
            run_submission(choice, (SAMPLES / choice).read_bytes())
    else:
        st.caption("Run `python scripts/make_sample_invoices.py` to create demo invoices.")

last = st.session_state.get("_last_submission")
if last:
    inv = data.invoice(last)
    with st.container(border=True):
        st.html(f"<div style='display:flex;gap:8px;align-items:center;flex-wrap:wrap'><b>{esc(inv['invoice_number'] or inv['file_name'])}</b>"
                f"{status_badge(inv['status'])}{verification_badge(inv)}<span class='ig-subtitle'>"
                f"Extraction: {esc(inv['extraction_strategy'] or 'none')} · confidence {(inv['confidence'] or 0):.2f}"
                f"</span></div>")
        v = inv.get("validation") or {}
        if v.get("errors"):
            notice("danger", "Validation errors", [f"{e['code']}: {e['message']}" for e in v["errors"]])
        if v.get("warnings"):
            notice("warning", "Warnings", [f"{w['code']}: {w['message']}" for w in v["warnings"]])
        if inv["escalation_reason"] and inv["status"] == "ESCALATED":
            notice("warning", "Sent for manual review", body=inv["escalation_reason"])
        if inv["status"] == "AWAITING_APPROVAL":
            notice("success", "Verified and waiting for an accounts manager")
        if st.button("Open in Invoice Review", icon=":material/fact_check:"):
            st.session_state["review_invoice_id"] = inv["id"]
            st.switch_page(PAGES["review"][0])

st.html('<div class="ig-section-title">My invoices</div>')
mine = data.invoices(uploader_id=user["id"])
if not mine:
    empty_state("You have not submitted any invoices yet", "Use the upload area above.")
    st.stop()
f1, f2 = st.columns([3, 2])
q = f1.text_input("Search", placeholder="Invoice number, supplier or file name", label_visibility="collapsed")
statuses = f2.multiselect("Status", [s for s in STATUS_STYLE], format_func=status_label, placeholder="All statuses",
                          label_visibility="collapsed")
rows = [i for i in mine if (not statuses or i["status"] in statuses) and
        (not q or q.lower() in f"{i['invoice_number']} {i['supplier_name']} {i['file_name']} {i['id']}".lower())]
table = pd.DataFrame([{"Invoice": i["invoice_number"] or i["file_name"], "Supplier": i["supplier_name"] or "-",
                       "Amount": money(i["grand_total"]), "Status": status_label(i["status"]),
                       "Verification": verification(i)[0], "Submitted": pd.Timestamp(i["created_at"]).strftime("%d %b, %H:%M"),
                       "ID": i["id"]} for i in rows])
if table.empty:
    st.caption("No invoices match the filters.")
else:
    ev = st.dataframe(table, hide_index=True, width="stretch", on_select="rerun", selection_mode="single-row",
                      key="my_invoices")
    if ev and ev.selection.rows:
        picked = rows[ev.selection.rows[0]]
        st.session_state["review_invoice_id"] = picked["id"]
        st.switch_page(PAGES["review"][0])
    st.caption("Select a row to open it in Invoice Review.")
