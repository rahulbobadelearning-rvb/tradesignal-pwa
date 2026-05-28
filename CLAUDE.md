# CLAUDE.md — Invoice Approval Tool

Guidance for Claude Code (and contributors) working in this repo.
Read this before writing or modifying any code.

---

## Repo purpose

A **local-first, fully offline** invoice validation and approval tool for engineering
managers. No AI inference, no cloud calls, no external APIs — all logic is deterministic
and auditable. Data lives in `data/app.db` (SQLite) and `data/invoices/` (PDFs).

---

## Key commands

```bash
# First-time setup (HTTPS cert + password)
python scripts/setup_security.py

# Run the app
streamlit run app/main.py

# Run tests
python -m pytest tests/ -v

# Install / refresh dependencies
pip install -r requirements.txt
```

---

## Project layout

```
app/
  main.py            # Entry point: page config, CSS, auth gate, sidebar nav, routing
  core/
    auth.py          # PBKDF2-SHA256 auth, session timeout, rate limiting
    db.py            # SQLite CRUD + live migrations (_run_migrations)
    models.py        # Typed dataclasses: Vendor, Invoice, …
    analytics.py     # Historical metrics, PO runway calculations
    scoring.py       # Deterministic 100-pt confidence score
    pdf_utils.py     # Validation, SHA-256 hash, text extraction, path safety
    email_utils.py   # SMTP email alerts with Plotly chart attachments
    ui_tokens.py     # Maersk Design System constants + GLOBAL_CSS
  views/             # One render() function per page
    dashboard.py
    vendor_master.py
    upload_invoice.py
    invoice_search.py
    vendor_detail.py
    settings.py
scripts/
  setup_security.py  # Generates self-signed TLS cert, writes .streamlit/config.toml
tests/
  test_scoring.py
data/                # gitignored at runtime
  app.db
  invoices/
  .credentials
  .smtp_config.json
```

> **Critical naming rule:** view modules live in `views/`, NOT `pages/`.
> Streamlit auto-detects any directory named `pages/` and builds its own
> navigation, which would duplicate the sidebar radio.  Never rename `views/`.

---

## State management pattern

All transient UI state is stored in **`st.session_state`** — the single source of
truth for every interaction that must survive a Streamlit rerun within a session.
There is no external state store, no database writes for ephemeral UI state, and no
global Python variables for per-session data.

### Canonical session state keys

| Key | Type | Owner | Lifetime | Purpose |
|---|---|---|---|---|
| `authenticated` | `bool` | `core/auth.py` | Session | Whether the user has passed the login gate |
| `last_active` | `float` (Unix timestamp) | `core/auth.py` | Session | Tracks idle time; refreshed on every page render |
| `login_attempts` | `int` | `core/auth.py` | Session | Failed login count for rate-limit enforcement |
| `last_attempt_time` | `float` | `core/auth.py` | Session | Timestamp of last failed attempt; used to expire lockout |
| `confirm_delete` | `int` (invoice ID) | `views/invoice_search.py` | Transient | Stores the invoice ID awaiting the second click to confirm deletion |
| `email_result_{vid}` | `tuple[str, str]` | `views/dashboard.py` | Transient | Caches the `("ok"/"error", message)` result of the last email send per vendor |
| `detail_vendor_label` | `str` | `views/vendor_detail.py` | Cross-page | Pre-selects a vendor when navigating to Vendor Detail from another page |

### Rules for adding new state

1. **Name keys by `{module}_{purpose}`** (e.g. `upload_preview_bytes`) to avoid
   collisions between views.
2. **Read defensively with `.get(key, default)`** — never assume a key is already
   initialised, because Streamlit can create a fresh session at any time.
3. **Use `.pop(key, None)`** to clean up transient state after it has been consumed
   (e.g. after a delete confirmation is acted on).
4. **Never store large blobs** (raw PDF bytes, DataFrames) in session state; store
   only identifiers (IDs, file paths) and re-read from DB/disk on demand.
5. **Auth keys are managed exclusively by `core/auth.py`.**  No view should write
   `authenticated` or `last_active` directly — call `logout()` instead.
6. **Cross-page navigation state** (e.g. `detail_vendor_label`) is set by the
   *source* view before triggering `st.rerun()`, and consumed + cleared by the
   *destination* view at the top of its `render()` function.

### Example — transient confirmation pattern

```python
# First click: arm the confirmation
if st.button("Delete"):
    st.session_state["confirm_delete"] = invoice_id

# Second click: execute and disarm
if st.session_state.get("confirm_delete") == invoice_id:
    if st.button("Confirm delete?", type="primary"):
        delete_invoice(invoice_id)
        st.session_state.pop("confirm_delete", None)
        st.rerun()
```

### Example — cross-page navigation

```python
# In the source view (e.g. dashboard.py):
st.session_state["detail_vendor_label"] = f"{vendor_code} – {vendor_name}"
st.rerun()  # main.py will route to Vendor Detail on next render

# In the destination view (vendor_detail.py), at the top of render():
preselect = st.session_state.get("detail_vendor_label")
# ... use preselect to set the selectbox index ...
# (do NOT pop it here — the selectbox default handles re-renders)
```

---

## Authentication architecture

- **Algorithm:** PBKDF2-SHA256, 260 000 iterations, 32-byte random salt (NIST SP 800-132)
- **Storage:** `data/.credentials` — `{salt_hex}:{hash_hex}`, owner-read only (`chmod 600`)
- **Comparison:** `hmac.compare_digest` for constant-time equality (prevents timing attacks)
- **Timeout:** 30-minute idle; `last_active` refreshed on every authenticated render
- **Rate limiting:** 5 failed attempts → 5-minute lockout (stored in session state, not DB)
- **Gate:** `login_required()` in `main.py` before any content renders; returns `False`
  and calls `st.stop()` implicitly via the caller pattern

---

## Database conventions

- **Single connection per request** — `get_connection()` opens and closes within each
  function call; no persistent connection objects stored on modules.
- **Live migrations** — `_run_migrations(conn)` in `db.py` runs every startup.
  Add new `ALTER TABLE … ADD COLUMN` statements there; wrap each in try/except
  `OperationalError` so they are idempotent on existing databases.
- **Never drop or rename columns** — existing deployments have real data.
  Add columns only; handle `NULL` values defensively in application code.

---

## Security rules (do not break)

| Rule | Where enforced |
|---|---|
| PDF files validated for `%PDF-` magic bytes and ≤ 20 MB | `core/pdf_utils.py · validate_pdf_bytes()` |
| Vendor codes match `^[A-Z0-9_-]{1,20}$` (prevents path traversal) | `core/pdf_utils.py · validate_vendor_code()` |
| Download paths resolved and checked against storage root | `core/pdf_utils.py · validate_download_path()` |
| All user strings HTML-escaped before `unsafe_allow_html=True` blocks | `html.escape()` in every view |
| SMTP credentials stored in `data/.smtp_config.json` (gitignored) | `core/email_utils.py` |
| TLS cert/key and `.credentials` are gitignored | `.gitignore` |

---

## UI / Design System

All visual constants (colours, spacing, border-radius, GLOBAL_CSS) are in
`core/ui_tokens.py`.  Never hardcode hex colours or pixel values in views — import
from `ui_tokens`.  The design follows **Maersk Design System** tokens:
spacing scale 4/8/16/24/32 px, card radius 8 px, accent `#009FCA`.

---

## Adding a new page

1. Create `app/views/my_page.py` with a single `render()` function.
2. Add a `("🔣", "My Page")` tuple to `NAV_ITEMS` in `main.py`.
3. Add an `elif selection == "My Page":` routing block in `main.py`.
4. Do **not** create a `pages/` directory or put files there.

---

## Dependencies

See `requirements.txt`.  All packages must work fully offline after installation.
Do not add packages that phone home, use telemetry, or require API keys.

Key packages and their roles:

| Package | Role |
|---|---|
| `streamlit` | UI framework |
| `pdfplumber` | PDF text extraction |
| `pandas` | DataFrame manipulation, Excel export |
| `plotly` | Interactive charts + PNG generation for emails |
| `openpyxl` | Excel file creation (styled .xlsx) |
| `kaleido` | Plotly → static PNG (used by email_utils) |
| `cryptography` | RSA-2048 self-signed TLS cert generation |
| `python-dateutil` | Robust date parsing from invoice text |
