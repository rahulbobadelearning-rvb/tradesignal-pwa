# REMARK: The confidence score is fully deterministic — given the same
# inputs you always get the same output.  Every component is weighted,
# labelled, and logged so the approver can audit the decision without
# needing to understand any algorithm.

from typing import Optional

from core.analytics import get_vendor_analytics
from core.db import check_duplicate
from core.models import ConfidenceResult, ScoreBreakdown

# ---------------------------------------------------------------------------
# Weights — must sum to 100
# ---------------------------------------------------------------------------
WEIGHT_UNIQUENESS: int = 25
WEIGHT_DEVIATION: int = 25
WEIGHT_BUDGET: int = 25
WEIGHT_COMPLETENESS: int = 25

# Deviation thresholds (fraction of average)
DEVIATION_LOW: float = 0.05    # ≤ 5 %  → full score
DEVIATION_MED: float = 0.10    # ≤ 10 % → moderate penalty
DEVIATION_HIGH: float = 0.20   # ≤ 20 % → heavy penalty
# > 20 % → maximum penalty

APPROVAL_THRESHOLD: float = 90.0


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def score_invoice(
    vendor_id: int,
    invoice_number: Optional[str],
    invoice_amount: float,
    service_month: str,
    pdf_hash: Optional[str],
    po_value: float,
) -> ConfidenceResult:
    """
    Compute a 0–100 confidence score from four independent rule components.
    Hard fails (duplicates, exhausted PO) short-circuit to Hard Reject.
    """
    flags: list[str] = []
    breakdown: list[ScoreBreakdown] = []

    # ── 1. Uniqueness ────────────────────────────────────────────────────
    u_score, u_note = _score_uniqueness(
        vendor_id, invoice_number, invoice_amount, service_month, pdf_hash, flags
    )
    breakdown.append(ScoreBreakdown(
        label="Invoice Uniqueness",
        raw_score=u_score,
        weight=WEIGHT_UNIQUENESS,
        weighted=u_score * WEIGHT_UNIQUENESS / 100,
        note=u_note,
    ))

    # ── 2. Amount deviation vs historical average ────────────────────────
    analytics = get_vendor_analytics(vendor_id)
    d_score, d_note = _score_deviation(invoice_amount, analytics.avg_monthly)
    breakdown.append(ScoreBreakdown(
        label="Amount Deviation",
        raw_score=d_score,
        weight=WEIGHT_DEVIATION,
        weighted=d_score * WEIGHT_DEVIATION / 100,
        note=d_note,
    ))

    # ── 3. Budget compliance ─────────────────────────────────────────────
    b_score, b_note = _score_budget(invoice_amount, po_value, analytics.ytd_spend, flags)
    breakdown.append(ScoreBreakdown(
        label="Monthly Budget Compliance",
        raw_score=b_score,
        weight=WEIGHT_BUDGET,
        weighted=b_score * WEIGHT_BUDGET / 100,
        note=b_note,
    ))

    # ── 4. Completeness ──────────────────────────────────────────────────
    c_score, c_note = _score_completeness(invoice_number, service_month)
    breakdown.append(ScoreBreakdown(
        label="Invoice Completeness",
        raw_score=c_score,
        weight=WEIGHT_COMPLETENESS,
        weighted=c_score * WEIGHT_COMPLETENESS / 100,
        note=c_note,
    ))

    # ── Final roll-up ────────────────────────────────────────────────────
    if flags:
        # Any hard-fail flag makes the entire invoice un-approvable
        total = 0.0
        recommendation = "Hard Reject"
    else:
        total = sum(b.weighted for b in breakdown)
        recommendation = "Approve" if total >= APPROVAL_THRESHOLD else "Needs Review"

    return ConfidenceResult(
        score=round(total, 1),
        recommendation=recommendation,
        breakdown=breakdown,
        flags=flags,
        avg_monthly=analytics.avg_monthly,
    )


# ---------------------------------------------------------------------------
# Component scoring helpers
# ---------------------------------------------------------------------------

def _score_uniqueness(
    vendor_id: int,
    invoice_number: Optional[str],
    invoice_amount: float,
    service_month: str,
    pdf_hash: Optional[str],
    flags: list[str],
) -> tuple[float, str]:
    reason = check_duplicate(vendor_id, invoice_number, invoice_amount, service_month, pdf_hash)
    if reason:
        flags.append(f"DUPLICATE: {reason}")
        return 0.0, f"Hard fail — {reason}"
    return 100.0, "No duplicate detected"


def _score_deviation(invoice_amount: float, avg_monthly: float) -> tuple[float, str]:
    if avg_monthly <= 0:
        # No history to compare against — award a neutral score
        return 75.0, "No historical average available (first invoice or new vendor)"

    deviation = abs(invoice_amount - avg_monthly) / avg_monthly

    if deviation <= DEVIATION_LOW:
        return 100.0, f"Within 5 % of average ({avg_monthly:,.2f})"

    if deviation <= DEVIATION_MED:
        # Linear interpolation: 100 → 75 over the 5–10 % band
        score = 100.0 - (deviation - DEVIATION_LOW) / (DEVIATION_MED - DEVIATION_LOW) * 25.0
        return round(score, 1), f"{deviation*100:.1f} % deviation — slight penalty (avg {avg_monthly:,.2f})"

    if deviation <= DEVIATION_HIGH:
        # Linear interpolation: 75 → 25 over the 10–20 % band
        score = 75.0 - (deviation - DEVIATION_MED) / (DEVIATION_HIGH - DEVIATION_MED) * 50.0
        return round(score, 1), f"{deviation*100:.1f} % deviation — moderate penalty (avg {avg_monthly:,.2f})"

    # > 20 %: heavy penalty, floor at 0
    score = max(0.0, 25.0 - (deviation - DEVIATION_HIGH) * 100.0)
    return round(score, 1), f"{deviation*100:.1f} % deviation — heavy penalty (avg {avg_monthly:,.2f})"


def _score_budget(
    invoice_amount: float,
    po_value: float,
    ytd_spend: float,
    flags: list[str],
) -> tuple[float, str]:
    if po_value <= 0:
        return 75.0, "No PO value configured — cannot assess budget compliance"

    projected = ytd_spend + invoice_amount
    if projected > po_value:
        flags.append(
            f"PO_EXHAUSTED: Projected YTD spend {projected:,.2f} exceeds PO value {po_value:,.2f}"
        )
        return 0.0, f"Hard fail — would exceed PO ({projected:,.2f} > {po_value:,.2f})"

    utilisation = projected / po_value

    if utilisation <= 0.80:
        return 100.0, f"PO utilisation {utilisation*100:.1f} % — healthy"
    if utilisation <= 0.95:
        return 75.0, f"PO utilisation {utilisation*100:.1f} % — approaching limit"
    return 50.0, f"PO utilisation {utilisation*100:.1f} % — very close to limit"


def _score_completeness(
    invoice_number: Optional[str],
    service_month: Optional[str],
) -> tuple[float, str]:
    score = 100.0
    missing = []

    if not invoice_number or not invoice_number.strip():
        score -= 50.0
        missing.append("invoice number")

    if not service_month or not service_month.strip():
        score -= 50.0
        missing.append("service month")

    if missing:
        return max(0.0, score), f"Missing: {', '.join(missing)}"
    return 100.0, "All required fields present"
