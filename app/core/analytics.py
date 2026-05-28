# REMARK: All business metrics live here so that pages stay thin.
# Every calculation is deterministic and derivable from the DB alone —
# no ML, no heuristics that can't be audited.

from datetime import date, datetime
from typing import Optional

from core.db import get_connection
from core.models import RunwayResult, VendorAnalytics


def get_vendor_analytics(vendor_id: int) -> VendorAnalytics:
    """
    Aggregate invoice history into summary metrics for a vendor.
    YTD is computed from January of the current calendar year.
    """
    current_year = str(datetime.now().year)

    with get_connection() as conn:
        rows = conn.execute(
            """
            SELECT service_month,
                   SUM(invoice_amount) AS monthly_total,
                   COUNT(*)            AS invoice_count
            FROM   invoices
            WHERE  vendor_id = ?
            GROUP  BY service_month
            ORDER  BY service_month
            """,
            (vendor_id,),
        ).fetchall()

    if not rows:
        return VendorAnalytics(
            avg_monthly=0.0,
            last_monthly=0.0,
            ytd_spend=0.0,
            monthly_totals={},
            monthly_counts={},
        )

    monthly_totals: dict[str, float] = {r["service_month"]: r["monthly_total"] for r in rows}
    monthly_counts: dict[str, int] = {r["service_month"]: r["invoice_count"] for r in rows}

    # Average across every month that has at least one invoice
    avg_monthly: float = sum(monthly_totals.values()) / len(monthly_totals)
    last_monthly: float = rows[-1]["monthly_total"]

    ytd_spend: float = sum(
        v for k, v in monthly_totals.items() if k.startswith(current_year)
    )

    return VendorAnalytics(
        avg_monthly=avg_monthly,
        last_monthly=last_monthly,
        ytd_spend=ytd_spend,
        monthly_totals=monthly_totals,
        monthly_counts=monthly_counts,
    )


def get_po_runway(
    vendor_id: int,
    po_value: float,
    po_expiration_date: Optional[str],
) -> RunwayResult:
    """
    Calculate how long the PO budget will last relative to spend pace.

    Logic:
      remaining_po     = po_value − ytd_spend
      expected_monthly = remaining_po / months_until_expiry
      on_track         = avg_monthly <= expected_monthly
    """
    analytics = get_vendor_analytics(vendor_id)
    remaining_po = po_value - analytics.ytd_spend

    if not po_expiration_date:
        return RunwayResult(
            remaining_po=remaining_po,
            months_remaining=None,
            expected_monthly=None,
            status="Unknown",
            on_track=None,
        )

    try:
        expiry = datetime.strptime(po_expiration_date, "%Y-%m-%d").date()
    except ValueError:
        return RunwayResult(
            remaining_po=remaining_po,
            months_remaining=None,
            expected_monthly=None,
            status="Unknown",
            on_track=None,
        )

    today = date.today()

    if expiry <= today:
        return RunwayResult(
            remaining_po=remaining_po,
            months_remaining=0,
            expected_monthly=0.0,
            status="Expired",
            on_track=False,
        )

    # Count calendar months between today and expiry (ceiling)
    months_remaining = _months_between(today, expiry)

    if remaining_po <= 0:
        return RunwayResult(
            remaining_po=remaining_po,
            months_remaining=months_remaining,
            expected_monthly=0.0,
            status="Risk",
            on_track=False,
        )

    expected_monthly = remaining_po / months_remaining if months_remaining > 0 else 0.0

    # "On track" means the average monthly spend fits within what's left
    on_track = (analytics.avg_monthly <= expected_monthly) if analytics.avg_monthly > 0 else True
    status = "On Track" if on_track else "Risk"

    return RunwayResult(
        remaining_po=remaining_po,
        months_remaining=months_remaining,
        expected_monthly=expected_monthly,
        status=status,
        on_track=on_track,
    )


def _months_between(start: date, end: date) -> int:
    """
    Returns the ceiling number of calendar months from start to end.
    Avoids python-dateutil so the dependency footprint stays small.
    """
    months = (end.year - start.year) * 12 + (end.month - start.month)
    if end.day > start.day:
        months += 1
    return max(1, months)


def get_dashboard_rows() -> list[dict]:
    """
    Returns one summary dict per vendor, ready for the dashboard table.
    Merges vendor master data with computed analytics and runway.
    """
    with get_connection() as conn:
        vendors = conn.execute("SELECT * FROM vendors ORDER BY vendor_name").fetchall()

    rows = []
    for v in vendors:
        analytics = get_vendor_analytics(v["id"])
        runway = get_po_runway(v["id"], v["po_value"], v["po_expiration_date"])
        rows.append(
            {
                "id": v["id"],
                "Vendor Name": v["vendor_name"],
                "Vendor Code": v["vendor_code"],
                "PO Number": v["po_number"] or "—",
                "PO Value": v["po_value"],
                "PO Expiration": v["po_expiration_date"] or "—",
                "Application Owner": v["application_owner"] or "—",
                "Avg Monthly": analytics.avg_monthly,
                "Last Monthly": analytics.last_monthly,
                "YTD Spend": analytics.ytd_spend,
                "Remaining PO": runway.remaining_po,
                "Months Left": runway.months_remaining,
                "Expected Monthly": runway.expected_monthly,
                "Runway Status": runway.status,
            }
        )
    return rows
