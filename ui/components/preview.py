"""Original-document viewer: page navigation, zoom, text highlights, document info and download."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.format import esc, when

ZOOM_DPI = {"Fit": 110, "125%": 140, "150%": 170, "200%": 220}


def document_preview(inv: dict, key: str, highlights: list[str] | None = None) -> None:
    path = Path(inv["file_path"])
    if not path.exists():
        st.warning("The original file is no longer available on disk.")
        return
    data = path.read_bytes()
    is_pdf = path.suffix.lower() == ".pdf"

    c1, c2 = st.columns([3, 2])
    zoom = c1.segmented_control("Zoom", list(ZOOM_DPI), default="Fit", key=f"{key}_zoom",
                                label_visibility="collapsed") or "Fit"
    c2.download_button("Download original", data, file_name=inv["file_name"], icon=":material/download:",
                       key=f"{key}_dl", width="stretch",
                       mime="application/pdf" if is_pdf else "image/png")

    if is_pdf:
        import pymupdf

        with pymupdf.open(path) as doc:
            n = len(doc)
            page_no = st.number_input(f"Page (of {n})", 1, n, 1, key=f"{key}_page") if n > 1 else 1
            page = doc[page_no - 1]
            for text in highlights or []:
                for rect in page.search_for(str(text)):
                    annot = page.add_highlight_annot(rect)
                    annot.set_colors(stroke=(1, 0.85, 0.35))
                    annot.update()
            png = page.get_pixmap(dpi=ZOOM_DPI[zoom]).tobytes("png")
        with st.container(height=640 if zoom != "Fit" else "content", border=True):
            st.image(png, width="content" if zoom != "Fit" else "stretch")
    else:
        with st.container(border=True):
            st.image(str(path), width="stretch")

    st.html(
        '<table class="ig-fields">'
        f'<tr><td class="ig-label">File</td><td class="ig-value">{esc(inv["file_name"])}</td></tr>'
        f'<tr><td class="ig-label">Size</td><td class="ig-value ig-num">{len(data) / 1024:,.1f} KB</td></tr>'
        f'<tr><td class="ig-label">Uploaded by</td><td class="ig-value">{esc(inv["uploader_id"])}</td></tr>'
        f'<tr><td class="ig-label">Received</td><td class="ig-value">{esc(when(inv["created_at"]))}</td></tr>'
        f'<tr><td class="ig-label">SHA-256</td><td class="ig-value ig-hash">{esc(inv["file_hash"] or "-")}</td></tr>'
        "</table>")
