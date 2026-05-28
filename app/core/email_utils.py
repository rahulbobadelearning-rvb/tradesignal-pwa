# REMARK: All email logic is isolated here so pages stay thin.
# We use Python's stdlib smtplib — zero cloud dependency.
# SMTP credentials are stored in data/.smtp_config.json (gitignored).
# Chart images are generated with plotly + kaleido (local rendering).

import base64
import json
import smtplib
import sys
from datetime import datetime
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path
from typing import Optional

from core.analytics import get_po_runway, get_vendor_analytics

# ---------------------------------------------------------------------------
# Config file (gitignored — never committed)
# ---------------------------------------------------------------------------
_PROJECT_ROOT = Path(__file__).parent.parent.parent
SMTP_CONFIG_PATH: Path = _PROJECT_ROOT / "data" / ".smtp_config.json"
RISK_RECIPIENT: str = "Rahul.bobade@maersk.com"


def load_smtp_config() -> dict:
    """Return stored SMTP settings or an empty template dict."""
    if SMTP_CONFIG_PATH.exists():
        try:
            return json.loads(SMTP_CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            pass
    return {
        "host": "smtp.office365.com",
        "port": 587,
        "username": "",
        "password": "",
        "sender_name": "Invoice Approval Tool",
        "sender_email": "",
    }


def save_smtp_config(config: dict) -> None:
    SMTP_CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    SMTP_CONFIG_PATH.write_text(json.dumps(config, indent=2), encoding="utf-8")
    try:
        SMTP_CONFIG_PATH.chmod(0o600)
    except NotImplementedError:
        pass


def smtp_configured() -> bool:
    cfg = load_smtp_config()
    return bool(cfg.get("host") and cfg.get("username") and cfg.get("sender_email"))


# ---------------------------------------------------------------------------
# Chart image generation
# ---------------------------------------------------------------------------

def _generate_chart_png(vendor_id: int, vendor_name: str) -> Optional[bytes]:
    """
    Render a spend-trend bar chart + PO utilisation gauge as a single PNG.
    Requires kaleido (installed separately).  Returns None on failure.
    """
    try:
        import plotly.graph_objects as go
        from plotly.subplots import make_subplots
        import plotly.io as pio

        analytics = get_vendor_analytics(vendor_id)
        months = sorted(analytics.monthly_totals.keys())
        amounts = [analytics.monthly_totals[m] for m in months]
        avg_line = [analytics.avg_monthly] * len(months)

        fig = make_subplots(
            rows=1, cols=2,
            column_widths=[0.65, 0.35],
            subplot_titles=["Monthly Spend", "PO Utilisation"],
            specs=[[{"type": "xy"}, {"type": "indicator"}]],
        )

        # Spend bar
        fig.add_trace(go.Bar(
            x=months, y=amounts,
            name="Monthly Spend", marker_color="#0073AB", opacity=0.85,
        ), row=1, col=1)

        # Average line
        if months:
            fig.add_trace(go.Scatter(
                x=months, y=avg_line, mode="lines",
                name=f"Avg ${analytics.avg_monthly:,.0f}",
                line=dict(color="#B45309", width=2, dash="dash"),
            ), row=1, col=1)

        # Gauge
        from core.db import get_vendor_by_id
        vendor = get_vendor_by_id(vendor_id)
        po_value = float(vendor["po_value"]) if vendor else 0.0
        pct = (analytics.ytd_spend / po_value * 100) if po_value > 0 else 0

        fig.add_trace(go.Indicator(
            mode="gauge+number",
            value=round(pct, 1),
            number=dict(suffix="%"),
            gauge=dict(
                axis=dict(range=[0, 100]),
                bar=dict(color="#B91C1C" if pct >= 80 else "#0073AB"),
                steps=[
                    dict(range=[0, 80],  color="#D1FAE5"),
                    dict(range=[80, 95], color="#FEF3C7"),
                    dict(range=[95, 100], color="#FEE2E2"),
                ],
            ),
        ), row=1, col=2)

        fig.update_layout(
            height=340, width=820,
            paper_bgcolor="white", plot_bgcolor="white",
            font=dict(size=11),
            margin=dict(l=20, r=20, t=40, b=20),
            showlegend=False,
        )

        return pio.to_image(fig, format="png", scale=2)

    except Exception as exc:
        print(f"[WARN] Chart generation failed: {exc}", file=sys.stderr)
        return None


# ---------------------------------------------------------------------------
# Email HTML body
# ---------------------------------------------------------------------------

def _build_html_body(vendor: dict, analytics, runway, chart_inline: bool = True) -> str:
    """Build a professional HTML email body with vendor risk data."""
    from html import escape
    remaining_po = runway.remaining_po
    months_left  = runway.months_remaining or "—"
    exp_monthly  = f"${runway.expected_monthly:,.0f}" if runway.expected_monthly else "—"

    # Monthly history table rows
    months = sorted(analytics.monthly_totals.keys())[-6:]   # last 6 months
    history_rows = "".join(
        f"<tr><td style='padding:4px 12px;'>{m}</td>"
        f"<td style='padding:4px 12px; text-align:right;'>${analytics.monthly_totals[m]:,.2f}</td></tr>"
        for m in months
    )

    chart_tag = '<img src="cid:vendor_chart" style="width:100%;max-width:820px;border-radius:6px;" alt="Spend chart">' \
        if chart_inline else "<p><i>(Chart unavailable)</i></p>"

    return f"""<!DOCTYPE html>
<html>
<head><meta charset="UTF-8"></head>
<body style="margin:0;padding:0;background:#F0F4F8;font-family:'Segoe UI',Arial,sans-serif;">
<table width="100%" cellpadding="0" cellspacing="0" style="max-width:860px;margin:24px auto;">

  <!-- Header -->
  <tr><td style="background:#0073AB;padding:24px 32px;border-radius:8px 8px 0 0;">
    <h1 style="color:#fff;margin:0;font-size:1.3rem;font-weight:700;">⚠ PO Risk Alert — Action Required</h1>
    <p style="color:rgba(255,255,255,.75);margin:4px 0 0;font-size:.85rem;">
      Invoice Approval Tool &nbsp;·&nbsp; {datetime.now().strftime('%d %b %Y %H:%M')}
    </p>
  </td></tr>

  <!-- Risk banner -->
  <tr><td style="background:#FEF3C7;border:1px solid #D97706;padding:14px 32px;">
    <strong style="color:#92400E;">Vendor <span style="color:#B45309;">{escape(vendor['vendor_name'])}</span>
    has reached a PO budget risk threshold.</strong><br>
    <span style="font-size:.85rem;color:#78350F;">
      At the current spend rate the PO may be exhausted before expiration.
      Please review and take action immediately.
    </span>
  </td></tr>

  <!-- Key metrics -->
  <tr><td style="background:#fff;padding:24px 32px;border:1px solid #E5E7EB;border-top:none;">
    <h2 style="font-size:1rem;margin:0 0 12px;color:#141414;">Vendor &amp; PO Details</h2>
    <table style="border-collapse:collapse;width:100%;font-size:.88rem;">
      <tr style="background:#F8FAFC;">
        <td style="padding:7px 14px;font-weight:600;width:220px;color:#5C6B7A;">Vendor Name</td>
        <td style="padding:7px 14px;">{escape(vendor['vendor_name'])}</td>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">Vendor Code</td>
        <td style="padding:7px 14px;">{escape(vendor['vendor_code'])}</td>
      </tr>
      <tr>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">PO Number</td>
        <td style="padding:7px 14px;">{escape(vendor['po_number'] or '—')}</td>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">Application Owner</td>
        <td style="padding:7px 14px;">{escape(vendor['application_owner'] or '—')}</td>
      </tr>
      <tr style="background:#F8FAFC;">
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">Country</td>
        <td style="padding:7px 14px;">{escape(vendor.get('country') or '—')}</td>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">PO Expiration</td>
        <td style="padding:7px 14px;">{escape(vendor['po_expiration_date'] or '—')}</td>
      </tr>
      <tr>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">PO Value</td>
        <td style="padding:7px 14px;">${vendor['po_value']:,.2f}</td>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">YTD Spend</td>
        <td style="padding:7px 14px;color:#B91C1C;font-weight:700;">${analytics.ytd_spend:,.2f}</td>
      </tr>
      <tr style="background:#FEE2E2;">
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">Remaining PO</td>
        <td style="padding:7px 14px;font-weight:700;color:#B91C1C;">${remaining_po:,.2f}</td>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">Months Left</td>
        <td style="padding:7px 14px;font-weight:700;color:#B91C1C;">{months_left}</td>
      </tr>
      <tr>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">Avg Monthly Spend</td>
        <td style="padding:7px 14px;">${analytics.avg_monthly:,.2f}</td>
        <td style="padding:7px 14px;font-weight:600;color:#5C6B7A;">Safe Monthly Budget</td>
        <td style="padding:7px 14px;">{exp_monthly}</td>
      </tr>
    </table>

    <!-- Chart -->
    <h2 style="font-size:1rem;margin:24px 0 12px;color:#141414;">Spend Trend &amp; PO Utilisation</h2>
    {chart_tag}

    <!-- Recent invoices -->
    <h2 style="font-size:1rem;margin:24px 0 12px;color:#141414;">Recent Monthly Spend (last 6 months)</h2>
    <table style="border-collapse:collapse;font-size:.85rem;min-width:280px;">
      <tr style="background:#0073AB;color:#fff;">
        <th style="padding:6px 12px;text-align:left;">Month</th>
        <th style="padding:6px 12px;text-align:right;">Amount</th>
      </tr>
      {history_rows}
    </table>

    <!-- Actions -->
    <h2 style="font-size:1rem;margin:24px 0 10px;color:#141414;">Recommended Actions</h2>
    <ol style="font-size:.88rem;line-height:1.8;color:#374151;">
      <li>Review current PO utilisation with the vendor and finance team.</li>
      <li><strong>Request a PO extension</strong> to cover the remaining contract period.</li>
      <li><strong>OR initiate a new PO creation</strong> to ensure service continuity.</li>
      <li>Update the PO value and expiration date in the Invoice Approval Tool once approved.</li>
    </ol>
  </td></tr>

  <!-- Footer -->
  <tr><td style="background:#E8F4FC;padding:12px 32px;border-radius:0 0 8px 8px;
                 text-align:center;font-size:.75rem;color:#5C6B7A;border:1px solid #E5E7EB;border-top:none;">
    This alert was sent automatically by the Invoice Approval Tool &nbsp;·&nbsp;
    100% local · no cloud · fully auditable
  </td></tr>

</table>
</body></html>"""


# ---------------------------------------------------------------------------
# Send email
# ---------------------------------------------------------------------------

def send_risk_alert(vendor_id: int) -> str:
    """
    Build and send a PO risk alert email for the given vendor.
    Returns an empty string on success, or an error message on failure.
    """
    cfg = load_smtp_config()
    if not smtp_configured():
        return "SMTP not configured. Go to Settings → Email to set up."

    from core.db import get_vendor_by_id
    vendor = get_vendor_by_id(vendor_id)
    if not vendor:
        return f"Vendor {vendor_id} not found."

    vendor = dict(vendor)
    analytics = get_vendor_analytics(vendor_id)
    runway = get_po_runway(vendor_id, vendor["po_value"], vendor.get("po_expiration_date"))

    # Try to render chart PNG
    chart_bytes = _generate_chart_png(vendor_id, vendor["vendor_name"])

    # Build MIME message
    msg = MIMEMultipart("related")
    msg["Subject"] = (
        f"\u26a0 PO Risk Alert: {vendor['vendor_name']} "
        f"({runway.status}) — Action Required"
    )
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender_email']}>"
    msg["To"] = RISK_RECIPIENT

    html_body = _build_html_body(vendor, analytics, runway, chart_inline=bool(chart_bytes))
    msg.attach(MIMEText(html_body, "html", "utf-8"))

    if chart_bytes:
        img = MIMEImage(chart_bytes, _subtype="png")
        img.add_header("Content-ID", "<vendor_chart>")
        img.add_header("Content-Disposition", "inline", filename="vendor_spend.png")
        msg.attach(img)

    # Send
    try:
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=15) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if cfg.get("username") and cfg.get("password"):
                server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["sender_email"], RISK_RECIPIENT, msg.as_bytes())
        return ""   # success
    except Exception as exc:
        print(f"[ERROR] Email send failed: {exc}", file=sys.stderr)
        return str(exc)
