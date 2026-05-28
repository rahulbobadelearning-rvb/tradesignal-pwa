# REMARK: Search gives the manager full read access — find, preview,
# download, and delete any invoice record.
# PDF viewer uses a base64-embedded iframe so no external server is needed.

import base64
from pathlib import Path

import pandas as pd
import streamlit as st

from core.db import delete_invoice, get_connection, list_invoices, list_vendors
from core.ui_tokens import COLOR_DANGER, COLOR_TEXT_SECONDARY


def render() -> None:
    st.markdown(
        "<h1 style='font-size:1.6rem; font-weight:800; margin-bottom:4px;'>Invoice Search</h1>"
        f"<p style='color:{COLOR_TEXT_SECONDARY}; font-size:0.85rem; margin-top:0;'>"
        "Search, preview, download, and manage uploaded invoices.</p>",
        unsafe_allow_html=True,
    )

    # ── Filter bar ────────────────────────────────────────────────────────────
    vendors = list_vendors()
    vendor_options = {"All Vendors": None}
    vendor_options.update({f"{v['vendor_name']} ({v['vendor_code']})": v["id"] for v in vendors})

    col1, col2, col3 = st.columns([2, 2, 2])
    with col1:
        vendor_label = st.selectbox("Vendor", list(vendor_options.keys()))
        vendor_id = vendor_options[vendor_label]
    with col2:
        search_text = st.text_input("Invoice number / amount",
                                     placeholder="INV-001 or 12500…")
    with col3:
        from datetime import datetime
        current_year = datetime.now().year
        month_opts = ["All Months"] + [
            f"{y}-{m:02d}"
            for y in range(current_year - 2, current_year + 2)
            for m in range(1, 13)
        ]
        selected_month = st.selectbox("Service Month", month_opts)

    # ── Fetch & filter ────────────────────────────────────────────────────────
    rows = list_invoices(vendor_id=vendor_id)

    if not rows:
        st.info("No invoices found. Upload invoices via **Upload Invoice**.")
        return

    df = _build_display_df(rows)

    if search_text:
        mask = (
            df["Invoice No"].str.contains(search_text, case=False, na=False)
            | df["Amount"].str.contains(search_text, case=False, na=False)
        )
        df = df[mask]

    if selected_month != "All Months":
        df = df[df["Service Month"] == selected_month]

    # ── Summary ───────────────────────────────────────────────────────────────
    total_shown = df["_amount_raw"].sum() if not df.empty else 0.0
    col_a, col_b = st.columns([3, 1])
    with col_a:
        st.caption(f"Showing **{len(df)}** of **{len(rows)}** invoices")
    with col_b:
        if not df.empty:
            st.caption(f"Total: **${total_shown:,.2f}**")

    if df.empty:
        st.warning("No invoices match the current filters.")
        return

    # ── Table ─────────────────────────────────────────────────────────────────
    display_cols = ["Vendor", "Code", "Invoice No", "Invoice Date",
                    "Service Month", "Amount", "Uploaded"]
    st.dataframe(df[display_cols], use_container_width=True,
                 hide_index=True, height=360)

    # ── Row-level actions ─────────────────────────────────────────────────────
    st.markdown("<hr class='mds-divider'>", unsafe_allow_html=True)
    st.markdown("<div class='mds-section-title'>Actions</div>",
                unsafe_allow_html=True)

    id_options = {
        f"#{r['id']} — {r['vendor_name']} | {r['invoice_number'] or 'No No.'} | "
        f"{r['service_month']} | ${r['invoice_amount']:,.2f}": r["id"]
        for r in rows
        if str(r["id"]) in df["_id"].values
    }

    if not id_options:
        return

    selected_label = st.selectbox("Select invoice", list(id_options.keys()))
    selected_id = id_options[selected_label]
    selected_row = next((r for r in rows if r["id"] == selected_id), None)

    # Three action buttons
    col_view, col_dl, col_del = st.columns([1, 1, 1])

    with col_view:
        view_clicked = st.button("👁️  View PDF", use_container_width=True)

    with col_dl:
        if selected_row and selected_row["pdf_path"]:
            from core.pdf_utils import validate_download_path
            try:
                safe_path = validate_download_path(Path(selected_row["pdf_path"]))
                if safe_path.exists():
                    pdf_bytes = safe_path.read_bytes()
                    st.download_button(
                        label="⬇️  Download PDF",
                        data=pdf_bytes,
                        file_name=safe_path.name,
                        mime="application/pdf",
                        use_container_width=True,
                    )
                else:
                    st.warning("PDF not found on disk.")
            except PermissionError:
                st.error("⛔ Access denied.")
        else:
            st.caption("No PDF attached.")

    with col_del:
        if st.button("🗑️  Delete Invoice", type="secondary", use_container_width=True):
            if st.session_state.get("confirm_delete") == selected_id:
                delete_invoice(selected_id)
                st.session_state.pop("confirm_delete", None)
                st.success("Invoice deleted.")
                st.rerun()
            else:
                st.session_state["confirm_delete"] = selected_id
                st.warning("Click **Delete Invoice** again to confirm.")

    # ── Inline PDF viewer ─────────────────────────────────────────────────────
    if view_clicked and selected_row and selected_row["pdf_path"]:
        _render_pdf_viewer(selected_row)


# ---------------------------------------------------------------------------
# PDF inline viewer
# ---------------------------------------------------------------------------

def _render_pdf_viewer(row: dict) -> None:
    from core.pdf_utils import validate_download_path
    st.markdown("<hr class='mds-divider'>", unsafe_allow_html=True)
    st.markdown("<div class='mds-section-title'>PDF Preview</div>",
                unsafe_allow_html=True)
    st.caption(
        f"**{row['vendor_name']}** · Invoice {row['invoice_number'] or '—'} · "
        f"{row['service_month']} · ${row['invoice_amount']:,.2f}"
    )

    try:
        safe_path = validate_download_path(Path(row["pdf_path"]))
        if not safe_path.exists():
            st.warning("PDF file not found on disk.")
            return
        pdf_bytes = safe_path.read_bytes()
        b64 = base64.b64encode(pdf_bytes).decode("utf-8")
        # REMARK: Embed as data URI in an iframe — works in all modern browsers
        # with no external server needed.  Chrome/Edge may require the user to
        # click "Allow" for inline PDFs from data URIs.
        pdf_html = (
            f'<iframe src="data:application/pdf;base64,{b64}" '
            f'width="100%" height="720px" '
            f'style="border:1px solid #D1D9E0; border-radius:8px;" '
            f'type="application/pdf">'
            f'<p>Your browser does not support inline PDF viewing. '
            f'Use the Download button above.</p>'
            f'</iframe>'
        )
        st.markdown(pdf_html, unsafe_allow_html=True)
    except PermissionError:
        st.error("⛔ Access denied: this file cannot be viewed.")
    except Exception as exc:
        st.error(f"Could not render PDF. Use the Download button instead.")


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _build_display_df(rows: list) -> pd.DataFrame:
    records = []
    for r in rows:
        records.append({
            "_id": str(r["id"]),
            "_amount_raw": r["invoice_amount"],
            "Vendor": r["vendor_name"],
            "Code": r["vendor_code"],
            "Invoice No": r["invoice_number"] or "—",
            "Invoice Date": r["invoice_date"] or "—",
            "Service Month": r["service_month"],
            "Amount": f"${r['invoice_amount']:,.2f}",
            "Uploaded": (r["upload_timestamp"] or "")[:10],
        })
    return pd.DataFrame(records)
