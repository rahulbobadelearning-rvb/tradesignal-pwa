# Invoice Approval Tool

A local-first, fully offline invoice validation and approval system for
engineering managers who receive vendor invoices monthly and must validate
them against historical spend and PO/contract limits.

---

## The 5-Year-Old Explanation

Imagine you get a bill every month from the people who help you.
This tool checks if the bill looks right — not too big, not already paid,
and within your budget — and gives you a score out of 100.
If the score is 90 or more, it says "looks good, approve it."
Otherwise it says "wait, check this first."
Everything happens on your own computer. Nothing goes to the internet.

---

## Quick Start

```bash
# 1. Create and activate a virtual environment
python -m venv .venv && .venv\Scripts\activate

# 2. Install dependencies
pip install -r requirements.txt

# 3. Launch the app
streamlit run app/main.py
```

Open your browser at **http://localhost:8501**.

---

## Remarks for Newcomers

**Where is the data?**
All data lives in `data/app.db` (SQLite) and `data/invoices/` (PDFs).
Both are gitignored. Never commit real invoice PDFs.

**How does the confidence score work?**
Four equally-weighted components (25 pts each):

| Component | What it checks |
|---|---|
| Invoice Uniqueness | PDF hash, invoice number, amount+month duplication |
| Amount Deviation | How far this invoice deviates from the vendor's historical average |
| Budget Compliance | Whether the invoice would exceed the remaining PO balance |
| Invoice Completeness | Whether invoice number and service month are filled in |

Any **hard fail** (duplicate, PO exhausted) forces the score to 0 and blocks saving.

**How do I add a vendor?**
Go to **Vendor Master → Add Vendor**. Every invoice must belong to a registered vendor.

**How do I run tests?**
```bash
python -m pytest tests/ -v
```

---

## Visual Logic Flow

```
Upload PDF
   │
   ▼
SHA-256 Hash  ──► Duplicate?  ──► Block upload
   │
   ▼
Extract text (best-effort: invoice no, date, amount)
   │
   ▼
User confirms / corrects invoice metadata
   │
   ▼
Score invoice
   │   ├─ Uniqueness check   (25 pts)
   │   ├─ Amount deviation   (25 pts)
   │   ├─ Budget compliance  (25 pts)
   │   └─ Completeness       (25 pts)
   │
   ▼
Hard fail? ──► Hard Reject (score = 0, cannot save)
   │
   ▼
Score ≥ 90? ──► ✅ Recommend Approve
   │
   └──────────► ⚠️ Needs Review (can still save with manual decision)
   │
   ▼
Save PDF + metadata to DB
```

---

## Project Structure

```
invoice-approval-tool/
├── app/
│   ├── main.py                # Streamlit entry point + navigation
│   ├── core/
│   │   ├── db.py              # SQLite access, CRUD helpers
│   │   ├── models.py          # Typed dataclasses (Vendor, Invoice, …)
│   │   ├── analytics.py       # Historical metrics, PO runway
│   │   ├── scoring.py         # Deterministic confidence score
│   │   ├── pdf_utils.py       # SHA-256 hash, text extraction, save
│   │   └── ui_tokens.py       # Maersk Design System visual constants
│   └── pages/
│       ├── dashboard.py       # Executive vendor overview
│       ├── vendor_master.py   # Vendor CRUD
│       ├── upload_invoice.py  # PDF upload + scoring
│       ├── invoice_search.py  # Search & download
│       └── vendor_detail.py   # Trend chart + full history
├── data/
│   ├── invoices/              # PDFs stored here (gitignored)
│   └── app.db                 # SQLite DB (gitignored)
├── tests/
│   └── test_scoring.py
├── README.md
├── PROMPT_LOG.md
├── .gitignore
└── requirements.txt
```

---

## Tech Stack

| Layer | Technology | Why |
|---|---|---|
| UI | Streamlit | Rapid, Python-native dashboard framework |
| Data | SQLite | Zero-config, file-based, portable |
| PDF | pdfplumber | Reliable text extraction; no cloud |
| Charts | Plotly | Interactive, no external data |
| Logic | Pure Python | Transparent, testable, auditable |

**No AI. No cloud. No network calls.**
