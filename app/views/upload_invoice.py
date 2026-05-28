# REMARK: Upload is the highest-stakes page — it is where duplicates are
# blocked, confidence is computed, and the approval recommendation is made.
# The flow is linear and intentionally visible so the manager can follow
# every decision step without needing documentation.

from datetime import date, datetime
from pathlib import Path
from typing import Optional

import streamlit as st

from core.db import (
    PDF_STORAGE,
    check_duplicate,
    get_vendor_by_code,
    insert_invoice,
    list_vendors,
)
from core.pdf_utils import (
    compute_sha256,
    extract_text,
    save_pdf,
    try_extract_amount,
    try_extract_date,
    try_extract_invoice_number,
)
from core.scoring import APPROVAL_THRESHOLD, score_invoice
from core.ui_tokens import (
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    status_badge,
)


def render() -> None:
    st.markdown(
        "<h1 style='font-size:1.6rem; font-weight:800; margin-bottom:4px;'>Upload Invoice</h1>"
        f"<p style='color:{COLOR_TEXT_SECONDARY}; font-size:0.85rem; margin-top:0;'>"
        "Upload a PDF invoice, review the confidence score, and save to the ledger.</p>",
        unsafe_allow_html=True,
    )

    vendors = list_vendors()
    if not vendors:
        st.error(
            "No vendors in the system. Please add a vendor in **Vendor Master** before uploading invoices."
        )
        return

    vendor_map = {f"{v['vendor_name']} ({v['vendor_code']})": v for v in vendors}

    # ── Step 1: choose vendor ─────────────────────────────────────────────────
    st.markdown("<div class='mds-section-title'>Step 1 — Select Vendor</div>", unsafe_allow_html=True)
    vendor_label = st.selectbox("Vendor", list(vendor_map.keys()), label_visibility="collapsed")
    vendor = vendor_map[vendor_label]

    st.markdown("<div class='mds-section-title' style='margin-top:16px;'>Step 2 — Upload PDF</div>", unsafe_allow_html=True)
    uploaded = st.file_uploader(
        "Invoice PDF",
        type=["pdf"],
        label_visibility="collapsed",
    )

    if not uploaded:
        st.info("Upload a PDF to continue.")
        return

    file_bytes = uploaded.read()

    # ── Server-side file validation ───────────────────────────────────────────
    # REMARK: The browser's type=["pdf"] filter is a UX hint only — it can be
    # bypassed.  We re-validate on the server using magic bytes and a hard size
    # cap to prevent malformed files or oversized uploads from reaching the parser.
    from core.pdf_utils import validate_pdf_bytes
    try:
        validate_pdf_bytes(file_bytes)
    except ValueError as exc:
        st.error(f"⛔ Upload rejected: {exc}")
        return

    pdf_hash = compute_sha256(file_bytes)

    # ── Fast duplicate check on hash alone ──────────────────────────────────
    from core.db import get_connection
    with get_connection() as conn:
        existing = conn.execute(
            "SELECT id FROM invoices WHERE pdf_hash = ?", (pdf_hash,)
        ).fetchone()
    if existing:
        st.error(
            f"⛔ This PDF has already been uploaded (invoice id={existing['id']}). "
            "Duplicate PDFs are not allowed."
        )
        return

    # ── Try auto-extraction from PDF text ────────────────────────────────────
    raw_text = extract_text(file_bytes)
    suggested_amount = try_extract_amount(raw_text)
    suggested_invoice_no = try_extract_invoice_number(raw_text)
    suggested_date = try_extract_date(raw_text)

    if any([suggested_amount, suggested_invoice_no, suggested_date]):
        with st.expander("🔍 Auto-extracted values from PDF (confirm or correct below)", expanded=True):
            cols = st.columns(3)
            cols[0].caption(f"Invoice No: **{suggested_invoice_no or '—'}**")
            cols[1].caption(f"Amount: **{f'${suggested_amount:,.2f}' if suggested_amount else '—'}**")
            cols[2].caption(f"Date: **{suggested_date or '—'}**")

    # ── Step 3: fill / confirm invoice details ───────────────────────────────
    st.markdown("<div class='mds-section-title' style='margin-top:16px;'>Step 3 — Invoice Details</div>", unsafe_allow_html=True)

    with st.form("invoice_form"):
        col1, col2 = st.columns(2)
        with col1:
            invoice_number = st.text_input(
                "Invoice Number",
                value=suggested_invoice_no or "",
                placeholder="INV-2024-001",
            )
            invoice_amount = st.number_input(
                "Invoice Amount *",
                min_value=0.01,
                value=float(suggested_amount) if suggested_amount else 0.01,
                step=100.0,
                format="%.2f",
            )

        with col2:
            # Service month selector (YYYY-MM)
            current_year = datetime.now().year
            month_options = [
                f"{y}-{m:02d}"
                for y in range(current_year - 1, current_year + 2)
                for m in range(1, 13)
            ]
            current_month = datetime.now().strftime("%Y-%m")
            default_idx = month_options.index(current_month) if current_month in month_options else 12
            service_month = st.selectbox(
                "Service Month (YYYY-MM) *",
                month_options,
                index=default_idx,
            )

            if suggested_date:
                try:
                    default_date = datetime.strptime(suggested_date, "%Y-%m-%d").date()
                except ValueError:
                    default_date = date.today()
            else:
                default_date = date.today()
            invoice_date = st.date_input("Invoice Date", value=default_date)

        submitted = st.form_submit_button("🧮  Compute Confidence & Preview", type="primary")

    if not submitted:
        return

    # ── Compute score ─────────────────────────────────────────────────────────
    result = score_invoice(
        vendor_id=vendor["id"],
        invoice_number=invoice_number.strip() or None,
        invoice_amount=invoice_amount,
        service_month=service_month,
        pdf_hash=pdf_hash,
        po_value=float(vendor["po_value"]),
    )

    # ── Display score card ────────────────────────────────────────────────────
    st.markdown("<hr class='mds-divider'>", unsafe_allow_html=True)
    st.markdown("<div class='mds-section-title'>Confidence Score</div>", unsafe_allow_html=True)

    score_class = (
        "score-approve" if result.recommendation == "Approve"
        else "score-reject" if result.recommendation == "Hard Reject"
        else "score-review"
    )
    icon = "✅" if result.recommendation == "Approve" else ("⛔" if result.recommendation == "Hard Reject" else "⚠️")

    col_score, col_detail = st.columns([1, 2])

    with col_score:
        st.markdown(
            f"""
            <div class='score-block'>
              <div class='score-number {score_class}'>{result.score}</div>
              <div style='font-size:0.7rem; color:{COLOR_TEXT_SECONDARY}; margin:4px 0 8px;'>/ 100</div>
              <div style='font-weight:700; font-size:1rem;'>{icon} {result.recommendation}</div>
              <div style='font-size:0.72rem; color:{COLOR_TEXT_SECONDARY}; margin-top:4px;'>
                Threshold: {APPROVAL_THRESHOLD:.0f}
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

    with col_detail:
        # Score breakdown table
        st.markdown("**Score Breakdown**")
        for b in result.breakdown:
            bar_color = COLOR_SUCCESS if b.raw_score >= 80 else (COLOR_WARNING if b.raw_score >= 50 else COLOR_DANGER)
            pct = int(b.raw_score)
            st.markdown(
                f"""
                <div style='margin-bottom:8px;'>
                  <div style='display:flex; justify-content:space-between; font-size:0.82rem;'>
                    <span>{b.label}</span>
                    <span style='font-weight:700;'>{b.raw_score:.0f}/100 × {b.weight}%
                      = <b>{b.weighted:.1f} pts</b></span>
                  </div>
                  <div style='background:#E5E7EB; border-radius:4px; height:6px; margin:3px 0;'>
                    <div style='background:{bar_color}; width:{pct}%; height:6px; border-radius:4px;'></div>
                  </div>
                  <div style='font-size:0.75rem; color:{COLOR_TEXT_SECONDARY};'>{b.note}</div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    # Hard-fail flags
    if result.flags:
        st.markdown("**Hard-Fail Flags**")
        for flag in result.flags:
            st.error(f"⛔ {flag}")
        st.warning("This invoice cannot be saved while hard-fail conditions exist.")
        return

    # Historical context
    if result.avg_monthly > 0:
        deviation_pct = (invoice_amount - result.avg_monthly) / result.avg_monthly * 100
        direction = "above" if deviation_pct > 0 else "below"
        st.caption(
            f"This invoice is **{abs(deviation_pct):.1f} % {direction}** the vendor's "
            f"historical average of **${result.avg_monthly:,.2f}**."
        )

    # ── Save confirmation ─────────────────────────────────────────────────────
    st.markdown("<hr class='mds-divider'>", unsafe_allow_html=True)

    if result.recommendation == "Approve":
        st.success("✅ Confidence is sufficient. You may save this invoice.")
    else:
        st.warning("⚠️ Confidence is below threshold. Review carefully before saving.")

    if st.button("💾  Save Invoice to Ledger", type="primary"):
        pdf_dest = save_pdf(file_bytes, uploaded.name, vendor["vendor_code"])
        insert_invoice(
            vendor_id=vendor["id"],
            invoice_number=invoice_number.strip() or None,
            invoice_date=invoice_date.strftime("%Y-%m-%d") if invoice_date else None,
            service_month=service_month,
            invoice_amount=invoice_amount,
            pdf_path=str(pdf_dest),
            pdf_hash=pdf_hash,
        )
        st.success(
            f"✅ Invoice saved! Vendor: **{vendor['vendor_name']}** | "
            f"Month: **{service_month}** | Amount: **${invoice_amount:,.2f}**"
        )
        st.balloons()
