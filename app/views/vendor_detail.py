# REMARK: The Vendor Detail view is where the manager can read the full
# spend story for one vendor: trend chart, invoice-by-invoice history,
# and PO runway gauge.  All data is computed on the fly from the DB —
# no pre-computed caches, so it's always fresh.

from datetime import datetime

import pandas as pd
import plotly.graph_objects as go
import streamlit as st

from core.analytics import get_po_runway, get_vendor_analytics
from core.db import list_invoices, list_vendors
from core.ui_tokens import (
    COLOR_ACCENT,
    COLOR_BG_CARD,
    COLOR_BORDER,
    COLOR_DANGER,
    COLOR_SUCCESS,
    COLOR_TEXT_SECONDARY,
    COLOR_WARNING,
    status_badge,
)


def render() -> None:
    st.markdown(
        "<h1 style='font-size:1.6rem; font-weight:800; margin-bottom:4px;'>Vendor Detail</h1>"
        f"<p style='color:{COLOR_TEXT_SECONDARY}; font-size:0.85rem; margin-top:0;'>"
        "Monthly spend trend, PO runway, and full invoice history per vendor.</p>",
        unsafe_allow_html=True,
    )

    vendors = list_vendors()
    if not vendors:
        st.info("No vendors yet. Add vendors in **Vendor Master** first.")
        return

    # Allow pre-selection via session state (e.g. from dashboard click)
    vendor_map = {f"{v['vendor_name']} ({v['vendor_code']})": v for v in vendors}
    preselect = st.session_state.get("detail_vendor_label")
    default_idx = list(vendor_map.keys()).index(preselect) if preselect in vendor_map else 0

    vendor_label = st.selectbox("Select vendor", list(vendor_map.keys()), index=default_idx)
    vendor = vendor_map[vendor_label]

    analytics = get_vendor_analytics(vendor["id"])
    runway = get_po_runway(vendor["id"], vendor["po_value"], vendor["po_expiration_date"])

    # ── KPI strip ─────────────────────────────────────────────────────────────
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Avg Monthly", f"${analytics.avg_monthly:,.0f}")
    c2.metric("Last Monthly", f"${analytics.last_monthly:,.0f}")
    c3.metric("YTD Spend", f"${analytics.ytd_spend:,.0f}")
    c4.metric("PO Remaining", f"${runway.remaining_po:,.0f}")
    c5.metric(
        "Runway Status",
        runway.status,
    )

    st.markdown("<hr class='mds-divider'>", unsafe_allow_html=True)

    # ── Two-column layout: trend + runway ─────────────────────────────────────
    col_trend, col_runway = st.columns([3, 2])

    with col_trend:
        _render_trend_chart(vendor, analytics)

    with col_runway:
        _render_runway_gauge(vendor, analytics, runway)

    st.markdown("<hr class='mds-divider'>", unsafe_allow_html=True)

    # ── Invoice history table ─────────────────────────────────────────────────
    st.markdown("<div class='mds-section-title'>Invoice History</div>", unsafe_allow_html=True)
    _render_invoice_history(vendor["id"])


# ---------------------------------------------------------------------------
# Sub-renders
# ---------------------------------------------------------------------------

def _render_trend_chart(vendor: dict, analytics: "VendorAnalytics") -> None:
    st.markdown("<div class='mds-section-title'>Monthly Spend Trend</div>", unsafe_allow_html=True)

    if not analytics.monthly_totals:
        st.info("No invoice history yet.")
        return

    months = sorted(analytics.monthly_totals.keys())
    amounts = [analytics.monthly_totals[m] for m in months]
    avg_line = [analytics.avg_monthly] * len(months)

    fig = go.Figure()

    # Bar: actual monthly spend
    fig.add_trace(
        go.Bar(
            x=months,
            y=amounts,
            name="Monthly Spend",
            marker_color=COLOR_ACCENT,
            opacity=0.85,
        )
    )

    # Line: historical average
    fig.add_trace(
        go.Scatter(
            x=months,
            y=avg_line,
            mode="lines",
            name=f"Avg (${analytics.avg_monthly:,.0f})",
            line=dict(color=COLOR_WARNING, width=2, dash="dash"),
        )
    )

    fig.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=24, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(size=11),
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        xaxis=dict(gridcolor="#E5E7EB", tickangle=-30),
        yaxis=dict(gridcolor="#E5E7EB", tickprefix="$", tickformat=",.0f"),
        bargap=0.3,
    )

    st.plotly_chart(fig, use_container_width=True)

    # Multi-invoice months warning
    multi = {m: c for m, c in analytics.monthly_counts.items() if c > 1}
    if multi:
        st.caption(
            f"⚠️ Multiple invoices in: "
            + ", ".join(f"**{m}** ({c})" for m, c in sorted(multi.items()))
        )


def _render_runway_gauge(vendor: dict, analytics: "VendorAnalytics", runway: "RunwayResult") -> None:
    st.markdown("<div class='mds-section-title'>PO Runway</div>", unsafe_allow_html=True)

    po_value = float(vendor["po_value"])
    ytd_spend = analytics.ytd_spend
    pct_used = (ytd_spend / po_value * 100) if po_value > 0 else 0

    # Gauge chart
    gauge_color = (
        COLOR_SUCCESS if runway.on_track and pct_used < 80
        else COLOR_WARNING if pct_used < 95
        else COLOR_DANGER
    )

    fig = go.Figure(
        go.Indicator(
            mode="gauge+number+delta",
            value=pct_used,
            number=dict(suffix="%", font=dict(size=28)),
            delta=dict(
                reference=80,
                increasing=dict(color=COLOR_DANGER),
                decreasing=dict(color=COLOR_SUCCESS),
            ),
            gauge=dict(
                axis=dict(range=[0, 100], ticksuffix="%"),
                bar=dict(color=gauge_color),
                steps=[
                    dict(range=[0, 80], color="#D1FAE5"),
                    dict(range=[80, 95], color="#FEF3C7"),
                    dict(range=[95, 100], color="#FEE2E2"),
                ],
                threshold=dict(line=dict(color=COLOR_DANGER, width=2), thickness=0.75, value=100),
            ),
            title=dict(text="YTD PO Utilisation", font=dict(size=13)),
        )
    )
    fig.update_layout(
        height=260,
        margin=dict(l=16, r=16, t=32, b=0),
        paper_bgcolor="rgba(0,0,0,0)",
    )
    st.plotly_chart(fig, use_container_width=True)

    # Runway detail rows
    # REMARK: html.escape() applied to all user-supplied strings before they
    # are embedded in an unsafe_allow_html block.  Numeric values are
    # formatted by Python (not user-controlled) so they are safe as-is.
    import html as _html
    safe_expiry = _html.escape(str(vendor["po_expiration_date"] or "—"))
    safe_months = _html.escape(str(runway.months_remaining if runway.months_remaining is not None else "—"))
    safe_expected = _html.escape(
        "${:,.0f}".format(runway.expected_monthly) if runway.expected_monthly else "—"
    )
    safe_status_badge = status_badge(runway.status)  # status_badge returns a fixed set of strings

    st.markdown(
        f"""
        <div style='font-size:0.82rem; line-height:1.8;'>
          <div><b>PO Value:</b> ${po_value:,.0f}</div>
          <div><b>YTD Spend:</b> ${ytd_spend:,.0f}</div>
          <div><b>Remaining:</b> ${runway.remaining_po:,.0f}</div>
          <div><b>PO Expiration:</b> {safe_expiry}</div>
          <div><b>Months Left:</b> {safe_months}</div>
          <div><b>Expected Monthly:</b> {safe_expected}</div>
          <div><b>Status:</b> {safe_status_badge}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def _render_invoice_history(vendor_id: int) -> None:
    rows = list_invoices(vendor_id=vendor_id)

    if not rows:
        st.info("No invoices for this vendor.")
        return

    records = [
        {
            "Service Month": r["service_month"],
            "Invoice No": r["invoice_number"] or "—",
            "Invoice Date": r["invoice_date"] or "—",
            "Amount": f"${r['invoice_amount']:,.2f}",
            "Has PDF": "✔" if r["pdf_path"] else "—",
            "Uploaded": (r["upload_timestamp"] or "")[:10],
        }
        for r in rows
    ]

    df = pd.DataFrame(records)
    st.dataframe(df, use_container_width=True, hide_index=True)
    st.caption(
        f"Total: **{len(rows)}** invoice{'s' if len(rows) != 1 else ''}  |  "
        f"Sum: **${sum(r['invoice_amount'] for r in rows):,.2f}**"
    )
