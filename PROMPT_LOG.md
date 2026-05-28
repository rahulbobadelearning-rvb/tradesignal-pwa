# Prompt Log

This file records what was built, why it exists, and any dependencies added.
It serves as an audit trail for the engineering manager and any future developers.

---

## Build 1 — Initial Release

**Date:** 2026-04-07
**Prompt tier:** Tier 1 — Architectural / Complex

### What was built

A fully local, offline invoice validation and approval tool with:

- **Vendor Master** — CRUD for vendor contracts (name, code, PO number, PO value, expiration, owner)
- **Invoice Upload** — PDF upload with SHA-256 deduplication, best-effort text extraction,
  and a deterministic 4-component confidence score
- **Dashboard** — Per-vendor executive overview: PO value, YTD spend, average monthly,
  last monthly, remaining PO, runway status (On Track / Risk / Expired)
- **Invoice Search** — Full-text + month filter, PDF download, single-invoice delete
- **Vendor Detail** — Monthly spend trend chart (Plotly), PO runway gauge, invoice history table
- **Confidence Scoring** — 0–100 score, threshold 90 = Approve, else Needs Review.
  Hard fails (duplicate, PO exhausted) force score to 0 and block saving.

### Why it exists

Engineering managers at DBH receive vendor invoices monthly and must validate them against:
- Historical spend patterns (is this amount unusual?)
- Remaining PO budget (will this exhaust the contract?)
- Duplicate risk (has this invoice already been paid?)

Manual spreadsheet tracking is error-prone and time-consuming. This tool makes the
validation process systematic, transparent, and auditable — with every decision
explained rather than opaque.

### Architectural decisions

| Decision | Reason |
|---|---|
| SQLite, not PostgreSQL | Zero-config, portable, runs on the manager's laptop |
| No AI / no LLM | Requirements explicitly forbid it; score must be auditable |
| Streamlit, not Flask | Avoids JS complexity; all business logic in Python |
| SHA-256 for deduplication | Content-based, collision-resistant, independent of filename |
| Weighted rule engine | Each component has a named weight so any score can be explained in plain English |

### Dependencies added

```
streamlit>=1.35.0      # UI framework
pdfplumber>=0.10.0     # PDF text extraction (no cloud, no OCR service)
pandas>=2.0.0          # DataFrame display and manipulation
plotly>=5.18.0         # Interactive trend + gauge charts
```

`python-dateutil` was considered for relativedelta but removed in favour of a
pure-stdlib `_months_between()` function to keep the dependency footprint minimal.

### Files created

```
app/main.py
app/core/db.py
app/core/models.py
app/core/analytics.py
app/core/scoring.py
app/core/pdf_utils.py
app/core/ui_tokens.py
app/pages/dashboard.py
app/pages/vendor_master.py
app/pages/upload_invoice.py
app/pages/invoice_search.py
app/pages/vendor_detail.py
tests/test_scoring.py
data/invoices/.gitkeep
requirements.txt
.gitignore
README.md
PROMPT_LOG.md
```

### Known limitations / future work

- PDF extraction is heuristic (regex-based); scanned/image PDFs will yield no auto-fill values.
  A future version could integrate a local OCR engine (Tesseract) without violating the no-cloud rule.
- The confidence score does not yet account for seasonal spend patterns (e.g. Q4 spikes).
- There is no user authentication — the tool assumes single-user, local execution.
- Multi-currency support is not implemented; amounts are stored as raw floats.
