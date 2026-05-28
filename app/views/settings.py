# REMARK: Settings page for SMTP email configuration.
# Credentials are stored locally in data/.smtp_config.json (gitignored).
# This page is intentionally minimal — it only stores what smtplib needs.

import streamlit as st

from core.email_utils import load_smtp_config, save_smtp_config, smtp_configured
from core.ui_tokens import COLOR_TEXT_SECONDARY


def render() -> None:
    st.markdown(
        "<h1 style='font-size:1.6rem; font-weight:800; margin-bottom:4px;'>Settings</h1>"
        f"<p style='color:{COLOR_TEXT_SECONDARY}; font-size:0.85rem; margin-top:0;'>"
        "Configure email alerts for PO risk notifications.</p>",
        unsafe_allow_html=True,
    )

    tab_email, tab_about = st.tabs(["📧  Email / SMTP", "ℹ️  About"])

    with tab_email:
        _render_smtp_form()

    with tab_about:
        _render_about()


def _render_smtp_form() -> None:
    st.markdown("<div class='mds-section-title'>SMTP Configuration</div>", unsafe_allow_html=True)

    if smtp_configured():
        st.success("✅ Email is configured. Risk alerts can be sent.")
    else:
        st.warning(
            "⚠️ Email is not configured yet. "
            "Fill in the fields below to enable PO risk alert emails."
        )

    cfg = load_smtp_config()

    with st.form("smtp_form"):
        col1, col2 = st.columns(2)

        with col1:
            st.markdown("**Server**")
            host = st.text_input("SMTP Host", value=cfg.get("host", "smtp.office365.com"),
                                  help="e.g. smtp.office365.com or smtp.gmail.com")
            port = st.number_input("SMTP Port", value=int(cfg.get("port", 587)),
                                    min_value=1, max_value=65535,
                                    help="587 for STARTTLS (recommended), 465 for SSL")
            username = st.text_input("Username / Email", value=cfg.get("username", ""),
                                      placeholder="your.name@maersk.com")
            password = st.text_input("Password", value=cfg.get("password", ""),
                                      type="password",
                                      help="Stored locally in data/.smtp_config.json (gitignored)")

        with col2:
            st.markdown("**Sender**")
            sender_name = st.text_input("Sender Name", value=cfg.get("sender_name", "Invoice Approval Tool"))
            sender_email = st.text_input("Sender Email", value=cfg.get("sender_email", ""),
                                          placeholder="invoices@maersk.com")
            st.markdown("**Recipient**")
            st.info("Risk alerts are always sent to:\n**Rahul.bobade@maersk.com**")

        saved = st.form_submit_button("💾  Save SMTP Settings", type="primary")

        if saved:
            if not host.strip() or not sender_email.strip():
                st.error("SMTP Host and Sender Email are required.")
            else:
                save_smtp_config({
                    "host": host.strip(),
                    "port": int(port),
                    "username": username.strip(),
                    "password": password,
                    "sender_name": sender_name.strip(),
                    "sender_email": sender_email.strip(),
                })
                st.success("✅ SMTP settings saved.")
                st.rerun()

    # Test email button
    st.markdown("<hr class='mds-divider'>", unsafe_allow_html=True)
    st.markdown("<div class='mds-section-title'>Test Connection</div>", unsafe_allow_html=True)

    if st.button("📤  Send Test Email", disabled=not smtp_configured()):
        _send_test_email()


def _send_test_email() -> None:
    import smtplib
    from email.mime.text import MIMEText
    from core.email_utils import load_smtp_config, RISK_RECIPIENT

    cfg = load_smtp_config()
    msg = MIMEText(
        "This is a test email from Invoice Approval Tool. "
        "If you received this, SMTP is configured correctly.",
        "plain",
    )
    msg["Subject"] = "Invoice Approval Tool — Test Email"
    msg["From"] = f"{cfg['sender_name']} <{cfg['sender_email']}>"
    msg["To"] = RISK_RECIPIENT

    try:
        with smtplib.SMTP(cfg["host"], int(cfg["port"]), timeout=10) as server:
            server.ehlo()
            server.starttls()
            server.ehlo()
            if cfg.get("username") and cfg.get("password"):
                server.login(cfg["username"], cfg["password"])
            server.sendmail(cfg["sender_email"], RISK_RECIPIENT, msg.as_bytes())
        st.success(f"✅ Test email sent successfully to {RISK_RECIPIENT}.")
    except Exception as exc:
        st.error(f"❌ Test failed: {exc}")


def _render_about() -> None:
    st.markdown(
        """
        ### Invoice Approval Tool
        **Version:** 1.1.0 · Local-first · No cloud · No AI

        | Component | Detail |
        |---|---|
        | UI | Streamlit (Maersk Design System–aligned) |
        | Database | SQLite (local file) |
        | Auth | PBKDF2-SHA256, session timeout |
        | Transport | HTTPS (self-signed cert) |
        | PDF | pdfplumber (local extraction) |
        | Email | Python smtplib (stdlib) |
        | Charts | Plotly + Kaleido |

        **Confidence Score Components (25 pts each)**
        1. Invoice Uniqueness — SHA-256 hash + invoice number + amount/month dedup
        2. Amount Deviation — vs historical average (< 5% → full score)
        3. Budget Compliance — projected YTD vs PO value
        4. Invoice Completeness — invoice number and service month present

        Threshold: **≥ 90 → Approve** · **< 90 → Needs Review**
        """
    )
