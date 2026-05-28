# REMARK: PDF handling is intentionally minimal — we store the original
# file untouched and attempt best-effort text extraction for convenience.
# SHA-256 hash is the canonical duplicate-detection mechanism because
# it is collision-resistant and content-based (independent of filename).

import hashlib
import re
import sys
from pathlib import Path
from typing import Optional

import pdfplumber

from core.db import PDF_STORAGE

# ---------------------------------------------------------------------------
# Security constants
# ---------------------------------------------------------------------------

# Maximum upload size (20 MB) — protects against memory exhaustion attacks
MAX_PDF_BYTES: int = 20 * 1024 * 1024

# PDF magic bytes — every valid PDF begins with %PDF-
_PDF_MAGIC: bytes = b"%PDF-"

# Allowed characters in vendor codes — prevents directory traversal via crafted codes
# Pattern: 1-20 uppercase alphanumeric + hyphen/underscore
_VENDOR_CODE_RE = re.compile(r'^[A-Z0-9_-]{1,20}$')


# ---------------------------------------------------------------------------
# Security validators
# ---------------------------------------------------------------------------

def validate_pdf_bytes(file_bytes: bytes) -> None:
    """
    Raise ValueError if the bytes are not a valid, safe-sized PDF.
    Checks file size and magic bytes — not just the browser-supplied MIME type,
    which is trivially spoofable by an attacker.
    """
    if len(file_bytes) > MAX_PDF_BYTES:
        raise ValueError(
            f"File too large ({len(file_bytes) // (1024*1024)} MB). "
            f"Maximum allowed size is {MAX_PDF_BYTES // (1024*1024)} MB."
        )
    if not file_bytes.startswith(_PDF_MAGIC):
        raise ValueError(
            "File does not appear to be a valid PDF (magic bytes check failed). "
            "Only genuine PDF files are accepted."
        )


def validate_vendor_code(vendor_code: str) -> str:
    """
    Return the sanitised vendor code or raise ValueError.
    Prevents directory traversal attacks via malicious vendor codes
    (e.g. '../../etc/passwd') that would be used as a directory name.
    """
    code = vendor_code.strip().upper()
    if not _VENDOR_CODE_RE.match(code):
        raise ValueError(
            "Vendor Code must be 1–20 characters: "
            "uppercase letters, numbers, hyphens, and underscores only."
        )
    return code


def sanitize_filename(filename: str) -> str:
    """
    Strip any directory component and replace unsafe characters.
    Prevents path traversal via crafted filenames like '../../secret.pdf'.
    """
    # Path.name strips any leading directory component
    name = Path(filename).name
    # Keep only safe characters
    name = re.sub(r"[^\w\-.]", "_", name)
    # Limit total length to prevent filesystem issues
    return name[:200] if name else "invoice.pdf"


def validate_download_path(pdf_path: Path) -> Path:
    """
    Resolve the path and verify it stays within PDF_STORAGE.
    Prevents path traversal in the download endpoint where a malicious
    DB record could point to arbitrary files outside the storage directory.
    """
    resolved = pdf_path.resolve()
    storage_resolved = PDF_STORAGE.resolve()
    try:
        resolved.relative_to(storage_resolved)
    except ValueError:
        raise PermissionError(
            f"Access denied: path is outside the invoice storage directory."
        )
    return resolved


# ---------------------------------------------------------------------------
# Core utilities
# ---------------------------------------------------------------------------

def compute_sha256(file_bytes: bytes) -> str:
    return hashlib.sha256(file_bytes).hexdigest()


def save_pdf(file_bytes: bytes, filename: str, vendor_code: str) -> Path:
    """
    Persist the uploaded PDF under data/invoices/<vendor_code>/<filename>.
    Both the vendor_code and filename are sanitised before use as path components.
    Returns the absolute path stored in the DB.
    """
    safe_code = validate_vendor_code(vendor_code)
    safe_name = sanitize_filename(filename)

    vendor_dir = PDF_STORAGE / safe_code
    vendor_dir.mkdir(parents=True, exist_ok=True)

    dest = vendor_dir / safe_name
    dest.write_bytes(file_bytes)
    return dest


def extract_text(file_bytes: bytes) -> str:
    """
    Return all text extracted from the PDF, concatenated page by page.
    Returns empty string on any extraction failure (corrupt, scanned, etc.).
    Errors are logged to stderr only — never surfaced to the browser.
    """
    try:
        import io
        with pdfplumber.open(io.BytesIO(file_bytes)) as pdf:
            pages = [page.extract_text() or "" for page in pdf.pages]
        return "\n".join(pages)
    except Exception as exc:
        print(f"[WARN] PDF text extraction failed: {exc}", file=sys.stderr)
        return ""


# ---------------------------------------------------------------------------
# Heuristic field extraction from raw PDF text
# These are "best effort" — the user always confirms values in the form.
# ---------------------------------------------------------------------------

_AMOUNT_RE = re.compile(
    r"""
    (?:total|amount\s+due|invoice\s+amount|grand\s+total|net\s+amount)
    [\s:]*
    [\$€£]?\s*
    ([\d,]+(?:\.\d{1,2})?)
    """,
    re.IGNORECASE | re.VERBOSE,
)
_INVOICE_NO_RE = re.compile(
    r"(?:invoice\s+(?:no|number|#|num)[.:]*\s*)([A-Z0-9\-/]+)",
    re.IGNORECASE,
)
_DATE_RE = re.compile(
    r"(?:invoice\s+date|date\s+of\s+invoice|issued)[.:]*\s*"
    r"(\d{1,2}[/\-\.]\d{1,2}[/\-\.]\d{2,4}|\d{4}[/\-]\d{2}[/\-]\d{2})"
    r"|(\b\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{4}\b)",
    re.IGNORECASE,
)


def try_extract_amount(text: str) -> Optional[float]:
    match = _AMOUNT_RE.search(text)
    if match:
        try:
            return float(match.group(1).replace(",", ""))
        except ValueError:
            return None
    return None


def try_extract_invoice_number(text: str) -> Optional[str]:
    match = _INVOICE_NO_RE.search(text)
    return match.group(1).strip() if match else None


def try_extract_date(text: str) -> Optional[str]:
    """Return date as ISO YYYY-MM-DD if parseable, else None."""
    match = _DATE_RE.search(text)
    if not match:
        return None
    raw = (match.group(1) or match.group(2) or "").strip()
    return _normalise_date(raw)


def _normalise_date(raw: str) -> Optional[str]:
    """Attempt to parse common date formats into ISO YYYY-MM-DD."""
    from datetime import datetime
    formats = [
        "%d/%m/%Y", "%m/%d/%Y", "%Y-%m-%d", "%d-%m-%Y",
        "%d.%m.%Y", "%d %B %Y", "%d %b %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(raw, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    return None
