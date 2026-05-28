# Basic unit tests for the confidence scoring logic.
# Run with:  python -m pytest tests/ -v
# (from the project root, after activating your venv)

import sys
from pathlib import Path

# Point Python at the app/ package so core.* imports resolve
# (views/ was formerly pages/ — renamed to avoid Streamlit's auto multipage detection)
sys.path.insert(0, str(Path(__file__).parent.parent / "app"))

from core.scoring import (
    APPROVAL_THRESHOLD,
    _score_budget,
    _score_completeness,
    _score_deviation,
    DEVIATION_HIGH,
    DEVIATION_LOW,
    DEVIATION_MED,
)


class TestDeviationScoring:
    def test_no_history_returns_neutral(self):
        score, _ = _score_deviation(1000.0, 0.0)
        assert score == 75.0

    def test_within_5pct_full_score(self):
        score, _ = _score_deviation(1030.0, 1000.0)  # 3 % deviation
        assert score == 100.0

    def test_10pct_deviation_moderate_penalty(self):
        score, _ = _score_deviation(1100.0, 1000.0)  # 10 %
        assert 74.0 <= score <= 76.0

    def test_25pct_deviation_heavy_penalty(self):
        score, _ = _score_deviation(1250.0, 1000.0)  # 25 %
        assert score < 25.0

    def test_exact_average_full_score(self):
        score, _ = _score_deviation(500.0, 500.0)
        assert score == 100.0


class TestBudgetScoring:
    def test_healthy_utilisation_full_score(self):
        score, _ = _score_budget(500.0, 10_000.0, 3_000.0, [])
        assert score == 100.0

    def test_over_po_hard_fail(self):
        flags: list = []
        score, _ = _score_budget(5_000.0, 10_000.0, 8_000.0, flags)
        assert score == 0.0
        assert any("PO_EXHAUSTED" in f for f in flags)

    def test_no_po_value_neutral_score(self):
        score, _ = _score_budget(1_000.0, 0.0, 0.0, [])
        assert score == 75.0


class TestCompletenessScoring:
    def test_all_fields_full_score(self):
        score, _ = _score_completeness("INV-001", "2024-03")
        assert score == 100.0

    def test_missing_invoice_number_half_penalty(self):
        score, _ = _score_completeness("", "2024-03")
        assert score == 50.0

    def test_both_missing_zero(self):
        score, _ = _score_completeness("", "")
        assert score == 0.0
