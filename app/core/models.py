# REMARK: Pure data classes — no DB logic here.  Keeps the domain model
# readable and allows functions in analytics / scoring to use typed objects
# rather than raw sqlite3.Row dicts.

from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Vendor:
    vendor_name: str
    vendor_code: str
    po_number: str
    po_value: float
    application_owner: str
    id: Optional[int] = None
    po_expiration_date: Optional[str] = None   # stored as ISO "YYYY-MM-DD"
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


@dataclass
class Invoice:
    vendor_id: int
    service_month: str      # "YYYY-MM"
    invoice_amount: float
    id: Optional[int] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None          # ISO "YYYY-MM-DD"
    pdf_path: Optional[str] = None
    pdf_hash: Optional[str] = None
    upload_timestamp: Optional[str] = None


@dataclass
class VendorAnalytics:
    """Derived metrics computed over a vendor's invoice history."""
    avg_monthly: float
    last_monthly: float
    ytd_spend: float
    monthly_totals: dict        # {"YYYY-MM": amount}
    monthly_counts: dict        # {"YYYY-MM": count}


@dataclass
class RunwayResult:
    remaining_po: float
    months_remaining: Optional[int]
    expected_monthly: Optional[float]
    status: str          # "On Track" | "Risk" | "Expired" | "Unknown"
    on_track: Optional[bool]


@dataclass
class ScoreBreakdown:
    label: str
    raw_score: float     # 0–100 component score
    weight: int          # percentage weight
    weighted: float      # raw_score * weight / 100
    note: str            # human-readable reason


@dataclass
class ConfidenceResult:
    score: float                          # 0–100 final score
    recommendation: str                   # "Approve" | "Needs Review" | "Hard Reject"
    breakdown: list[ScoreBreakdown] = field(default_factory=list)
    flags: list[str] = field(default_factory=list)
    avg_monthly: float = 0.0
