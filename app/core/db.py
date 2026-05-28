# REMARK: All DB access goes through this module.  Using a single
# SQLite file keeps everything portable — no server, no config, no data
# leaving the machine.  Row factory converts rows to dict-like objects
# so callers can use column names instead of positional indices.

import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

# Resolve data directory relative to this file's location:
#   app/core/db.py  →  ../../data/app.db  →  project_root/data/app.db
_PROJECT_ROOT = Path(__file__).parent.parent.parent
DB_PATH: Path = _PROJECT_ROOT / "data" / "app.db"
PDF_STORAGE: Path = _PROJECT_ROOT / "data" / "invoices"


def _ensure_dirs() -> None:
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    PDF_STORAGE.mkdir(parents=True, exist_ok=True)


def get_connection() -> sqlite3.Connection:
    _ensure_dirs()
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    # REMARK: Foreign key enforcement is OFF by default in SQLite —
    # we turn it on so cascade rules and referential integrity actually work.
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn


def now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def initialize_database() -> None:
    """Create tables if they don't exist.  Safe to call on every startup."""
    _ensure_dirs()
    with get_connection() as conn:
        conn.executescript("""
            -- ── Vendor master ─────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS vendors (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_name         TEXT    NOT NULL,
                vendor_code         TEXT    NOT NULL UNIQUE,
                po_number           TEXT,
                po_value            REAL    NOT NULL DEFAULT 0.0,
                po_expiration_date  TEXT,           -- ISO YYYY-MM-DD
                application_owner   TEXT,
                country             TEXT,
                created_at          TEXT    NOT NULL,
                updated_at          TEXT    NOT NULL
            );

        """)
        # REMARK: Live migration — adds new columns to existing databases
        # without requiring users to wipe and recreate their data.
        _run_migrations(conn)
        conn.executescript("""
            -- ── Invoice ledger ─────────────────────────────────────────────
            CREATE TABLE IF NOT EXISTS invoices (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                vendor_id           INTEGER NOT NULL REFERENCES vendors(id),
                invoice_number      TEXT,
                invoice_date        TEXT,           -- ISO YYYY-MM-DD
                service_month       TEXT    NOT NULL, -- YYYY-MM
                invoice_amount      REAL    NOT NULL,
                pdf_path            TEXT,
                pdf_hash            TEXT    UNIQUE, -- SHA-256 of the PDF binary
                upload_timestamp    TEXT    NOT NULL,
                FOREIGN KEY (vendor_id) REFERENCES vendors(id)
            );
        """)


def _run_migrations(conn: sqlite3.Connection) -> None:
    """Apply schema migrations for existing databases.  Each ALTER TABLE is
    wrapped in try/except — SQLite raises OperationalError if the column
    already exists, which we safely ignore."""
    migrations = [
        "ALTER TABLE vendors ADD COLUMN country TEXT",
    ]
    for sql in migrations:
        try:
            conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # Column already present — nothing to do


# ---------------------------------------------------------------------------
# Vendor CRUD
# ---------------------------------------------------------------------------

def list_vendors() -> list[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM vendors ORDER BY vendor_name"
        ).fetchall()


def get_vendor_by_id(vendor_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM vendors WHERE id = ?", (vendor_id,)
        ).fetchone()


def get_vendor_by_code(vendor_code: str) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM vendors WHERE vendor_code = ?", (vendor_code,)
        ).fetchone()


def insert_vendor(
    vendor_name: str,
    vendor_code: str,
    po_number: str,
    po_value: float,
    po_expiration_date: Optional[str],
    application_owner: str,
    country: Optional[str] = None,
) -> int:
    ts = now_iso()
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO vendors
                (vendor_name, vendor_code, po_number, po_value,
                 po_expiration_date, application_owner, country, created_at, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (vendor_name, vendor_code, po_number, po_value,
             po_expiration_date, application_owner, country, ts, ts),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def update_vendor(
    vendor_id: int,
    vendor_name: str,
    vendor_code: str,
    po_number: str,
    po_value: float,
    po_expiration_date: Optional[str],
    application_owner: str,
    country: Optional[str] = None,
) -> None:
    with get_connection() as conn:
        conn.execute(
            """
            UPDATE vendors
            SET vendor_name=?, vendor_code=?, po_number=?, po_value=?,
                po_expiration_date=?, application_owner=?, country=?, updated_at=?
            WHERE id=?
            """,
            (vendor_name, vendor_code, po_number, po_value,
             po_expiration_date, application_owner, country, now_iso(), vendor_id),
        )


def delete_vendor(vendor_id: int) -> None:
    # REMARK: We prevent deletion if invoices exist to protect data integrity.
    with get_connection() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM invoices WHERE vendor_id = ?", (vendor_id,)
        ).fetchone()[0]
        if count > 0:
            raise ValueError(
                f"Cannot delete: vendor has {count} invoice(s). Remove invoices first."
            )
        conn.execute("DELETE FROM vendors WHERE id = ?", (vendor_id,))


# ---------------------------------------------------------------------------
# Invoice CRUD
# ---------------------------------------------------------------------------

def list_invoices(vendor_id: Optional[int] = None) -> list[sqlite3.Row]:
    with get_connection() as conn:
        if vendor_id is not None:
            return conn.execute(
                """
                SELECT i.*, v.vendor_name, v.vendor_code
                FROM invoices i JOIN vendors v ON i.vendor_id = v.id
                WHERE i.vendor_id = ?
                ORDER BY i.service_month DESC, i.upload_timestamp DESC
                """,
                (vendor_id,),
            ).fetchall()
        return conn.execute(
            """
            SELECT i.*, v.vendor_name, v.vendor_code
            FROM invoices i JOIN vendors v ON i.vendor_id = v.id
            ORDER BY i.service_month DESC, i.upload_timestamp DESC
            """
        ).fetchall()


def get_invoice_by_id(invoice_id: int) -> Optional[sqlite3.Row]:
    with get_connection() as conn:
        return conn.execute(
            "SELECT * FROM invoices WHERE id = ?", (invoice_id,)
        ).fetchone()


def check_duplicate(
    vendor_id: int,
    invoice_number: Optional[str],
    invoice_amount: float,
    service_month: str,
    pdf_hash: Optional[str],
) -> Optional[str]:
    """Return a human-readable duplicate reason string, or None if clean."""
    with get_connection() as conn:
        if pdf_hash:
            row = conn.execute(
                "SELECT id FROM invoices WHERE pdf_hash = ?", (pdf_hash,)
            ).fetchone()
            if row:
                return f"PDF already uploaded (hash match, invoice id={row['id']})"

        if invoice_number and invoice_number.strip():
            row = conn.execute(
                "SELECT id FROM invoices WHERE vendor_id=? AND invoice_number=?",
                (vendor_id, invoice_number.strip()),
            ).fetchone()
            if row:
                return f"Invoice number '{invoice_number}' already exists for this vendor"

        row = conn.execute(
            "SELECT id FROM invoices WHERE vendor_id=? AND invoice_amount=? AND service_month=?",
            (vendor_id, invoice_amount, service_month),
        ).fetchone()
        if row:
            return f"Same amount ({invoice_amount}) already recorded for {service_month}"

    return None


def insert_invoice(
    vendor_id: int,
    invoice_number: Optional[str],
    invoice_date: Optional[str],
    service_month: str,
    invoice_amount: float,
    pdf_path: Optional[str],
    pdf_hash: Optional[str],
) -> int:
    with get_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO invoices
                (vendor_id, invoice_number, invoice_date, service_month,
                 invoice_amount, pdf_path, pdf_hash, upload_timestamp)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (vendor_id, invoice_number, invoice_date, service_month,
             invoice_amount, pdf_path, pdf_hash, now_iso()),
        )
        return cursor.lastrowid  # type: ignore[return-value]


def delete_invoice(invoice_id: int) -> None:
    with get_connection() as conn:
        conn.execute("DELETE FROM invoices WHERE id = ?", (invoice_id,))
