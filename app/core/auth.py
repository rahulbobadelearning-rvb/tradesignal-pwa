# REMARK: Single-user password authentication using PBKDF2-SHA256 (stdlib,
# NIST SP 800-132 compliant, 260k iterations).  No external auth library
# needed — keeps the dependency surface small for a local tool.
# All comparisons are constant-time to prevent timing-based enumeration.

import hashlib
import hmac
import os
import time
from pathlib import Path

import streamlit as st

from core.ui_tokens import COLOR_ACCENT, COLOR_BORDER, COLOR_TEXT_SECONDARY

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------
CREDS_FILE: Path = Path(__file__).parent.parent.parent / "data" / ".credentials"

SESSION_TIMEOUT_SECONDS: int = 30 * 60   # 30-minute idle timeout
MAX_LOGIN_ATTEMPTS: int = 5
LOCKOUT_SECONDS: int = 300               # 5-minute lockout after max attempts
PBKDF2_ITERATIONS: int = 260_000         # NIST minimum for PBKDF2-SHA256


# ---------------------------------------------------------------------------
# Password management
# ---------------------------------------------------------------------------

def hash_password(password: str, salt: bytes) -> str:
    """Derive a fixed-length hex digest from the password using PBKDF2-SHA256."""
    return hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, PBKDF2_ITERATIONS
    ).hex()


def set_password(password: str) -> None:
    """Hash and persist a new password.  Overwrites any existing credential."""
    if len(password) < 8:
        raise ValueError("Password must be at least 8 characters.")
    salt = os.urandom(32)
    hashed = hash_password(password, salt)
    CREDS_FILE.parent.mkdir(parents=True, exist_ok=True)
    CREDS_FILE.write_text(f"{salt.hex()}:{hashed}", encoding="utf-8")
    # Restrict to owner-read/write.  Silently ignored on Windows (NTFS handles
    # permissions via ACLs) but effective on macOS/Linux.
    try:
        CREDS_FILE.chmod(0o600)
    except NotImplementedError:
        pass


def verify_password(password: str) -> bool:
    """
    Verify a plaintext password against the stored hash.
    Uses hmac.compare_digest for constant-time comparison to prevent
    timing attacks that could leak whether the hash prefix matches.
    """
    if not CREDS_FILE.exists():
        return False
    stored = CREDS_FILE.read_text(encoding="utf-8").strip()
    try:
        salt_hex, stored_hash = stored.split(":", 1)
        salt = bytes.fromhex(salt_hex)
    except ValueError:
        return False
    computed = hash_password(password, salt)
    return hmac.compare_digest(computed, stored_hash)


def credentials_configured() -> bool:
    return CREDS_FILE.exists() and CREDS_FILE.stat().st_size > 64


# ---------------------------------------------------------------------------
# Streamlit session gate
# ---------------------------------------------------------------------------

def login_required() -> bool:
    """
    Call once at the top of main.py before rendering any content.
    Returns True only when the session is authenticated and not timed out.
    Renders the appropriate form (setup / login) and returns False otherwise.
    """
    if not credentials_configured():
        _show_first_time_setup()
        return False

    if st.session_state.get("authenticated"):
        last_active = st.session_state.get("last_active", 0.0)
        if time.time() - last_active > SESSION_TIMEOUT_SECONDS:
            # Timed out — clear state and re-prompt
            st.session_state.authenticated = False
            st.session_state.pop("last_active", None)
            st.warning(
                "⏰ Session timed out after 30 minutes of inactivity. "
                "Please log in again."
            )
            _show_login_form()
            return False
        # Refresh idle timer on every page interaction
        st.session_state.last_active = time.time()
        return True

    _show_login_form()
    return False


def logout() -> None:
    """Clear session and return to the login screen."""
    st.session_state.authenticated = False
    st.session_state.pop("last_active", None)
    st.rerun()


# ---------------------------------------------------------------------------
# UI helpers (private)
# ---------------------------------------------------------------------------

def _show_login_form() -> None:
    # Hide the sidebar while unauthenticated so no nav is accessible
    st.markdown(
        "<style>section[data-testid='stSidebar']{display:none!important;}</style>",
        unsafe_allow_html=True,
    )

    _, col, _ = st.columns([1, 1.1, 1])
    with col:
        st.markdown(
            f"""
            <div style="text-align:center; padding:48px 0 24px;">
              <div style="font-size:2rem; font-weight:800; color:{COLOR_ACCENT};
                          letter-spacing:-0.02em;">Invoice Approval</div>
              <div style="font-size:0.75rem; color:{COLOR_TEXT_SECONDARY};
                          text-transform:uppercase; letter-spacing:0.1em; margin-top:6px;">
                Vendor · PO · Compliance
              </div>
            </div>
            """,
            unsafe_allow_html=True,
        )

        with st.container():
            st.markdown(
                f"<div style='background:#fff; border:1px solid {COLOR_BORDER}; "
                f"border-radius:8px; padding:28px 24px 20px;'>",
                unsafe_allow_html=True,
            )
            with st.form("login_form", clear_on_submit=True):
                st.markdown("##### Sign in")
                password = st.text_input(
                    "Password", type="password", placeholder="Enter your password"
                )
                submitted = st.form_submit_button(
                    "Sign In →", type="primary", use_container_width=True
                )
            st.markdown("</div>", unsafe_allow_html=True)

        if submitted:
            _handle_login_attempt(password)


def _handle_login_attempt(password: str) -> None:
    attempts: int = st.session_state.get("login_attempts", 0)
    last_attempt: float = st.session_state.get("last_attempt_time", 0.0)

    # Enforce lockout window
    if attempts >= MAX_LOGIN_ATTEMPTS:
        elapsed = time.time() - last_attempt
        if elapsed < LOCKOUT_SECONDS:
            remaining = int(LOCKOUT_SECONDS - elapsed)
            st.error(
                f"⛔ Too many failed attempts. "
                f"Try again in {remaining // 60}m {remaining % 60}s."
            )
            return
        # Lockout expired — reset counter
        st.session_state.login_attempts = 0

    if verify_password(password):
        st.session_state.authenticated = True
        st.session_state.last_active = time.time()
        st.session_state.login_attempts = 0
        st.rerun()
    else:
        new_count = st.session_state.get("login_attempts", 0) + 1
        st.session_state.login_attempts = new_count
        st.session_state.last_attempt_time = time.time()
        remaining_attempts = MAX_LOGIN_ATTEMPTS - new_count
        if remaining_attempts > 0:
            st.error(
                f"❌ Incorrect password. "
                f"{remaining_attempts} attempt{'s' if remaining_attempts != 1 else ''} remaining."
            )
        else:
            st.error("⛔ Too many failed attempts. Account locked for 5 minutes.")


def _show_first_time_setup() -> None:
    _, col, _ = st.columns([1, 1.5, 1])
    with col:
        st.warning(
            "⚙️ **First-time setup required.**\n\n"
            "Run the following command to configure HTTPS and set your password:\n\n"
            "```\npython scripts/setup_security.py\n```\n\n"
            "Then restart the app."
        )
