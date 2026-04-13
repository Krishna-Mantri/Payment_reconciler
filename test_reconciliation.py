"""
Unit tests for the payments reconciliation engine.
Verifies all 4 planted gaps are correctly detected.

Run: pytest test_reconciliation.py -v
"""

import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

import pandas as pd
import pytest
from datetime import date

# Import from app
from app import generate_synthetic_data, run_reconciliation


@pytest.fixture(scope="module")
def data():
    platform_df, bank_df = generate_synthetic_data()
    results = run_reconciliation(platform_df, bank_df)
    return platform_df, bank_df, results


# ─────────────────────────────────────────────────────────────────
# GAP 1: Cross-month settlement
# ─────────────────────────────────────────────────────────────────

def test_cross_month_detected(data):
    """Dec 31 txn settling Jan 2, 2025 must appear in cross_month gap."""
    _, _, results = data
    cm = results["cross_month"]
    assert not cm.empty, "cross_month DataFrame should not be empty"
    assert len(cm) >= 1, "At least 1 cross-month txn expected"

    # Verify the settle date is in January 2025
    jan_settle = cm[cm["settle_date"].dt.month == 1]
    assert not jan_settle.empty, "Should find at least 1 Jan 2025 settle date"

    dec_txn = cm[cm["txn_date"].dt.day == 31]
    assert not dec_txn.empty, "Dec 31 txn should be in cross_month"


def test_cross_month_amount(data):
    """Cross-month txn should have amount $375.00."""
    _, _, results = data
    cm = results["cross_month"]
    amounts = cm["amount"].values
    assert 375.00 in amounts, f"Expected $375.00 cross-month txn, found: {amounts}"


# ─────────────────────────────────────────────────────────────────
# GAP 2: Rounding mismatches
# ─────────────────────────────────────────────────────────────────

def test_rounding_gaps_detected(data):
    """3 rounding mismatches should be flagged in amount_mismatches."""
    _, _, results = data
    am = results["amount_mismatches"]
    assert len(am) >= 3, f"Expected >= 3 rounding mismatches, got {len(am)}"


def test_rounding_gap_positive(data):
    """Platform total should exceed bank total for rounding txns (platform has cents)."""
    _, _, results = data
    am = results["amount_mismatches"]
    assert am["amount_diff"].sum() > 0, "Platform amounts should exceed bank due to flooring"


def test_rounding_specific_amounts(data):
    """Platform txns with $10.01, $10.99, $25.50 should show diffs vs bank."""
    _, bank_df, results = data
    am = results["amount_mismatches"]
    plat_amounts = set(am["amount_plat"].round(2).tolist())
    # At least two of the three seeded amounts should appear
    seeded = {10.01, 10.99, 25.50}
    overlap = plat_amounts & seeded
    assert len(overlap) >= 2, f"Expected seeded rounding amounts in mismatches, found overlap: {overlap}"


# ─────────────────────────────────────────────────────────────────
# GAP 3: Duplicate txn_id DUP123
# ─────────────────────────────────────────────────────────────────

def test_duplicate_dup123_detected(data):
    """DUP123 must appear in duplicates."""
    _, _, results = data
    dups = results["duplicates"]
    assert not dups.empty, "Duplicates DataFrame should not be empty"
    dup_ids = dups["txn_id"].tolist()
    assert "DUP123" in dup_ids, f"DUP123 not found in duplicates: {dup_ids}"


def test_duplicate_count(data):
    """DUP123 should appear exactly 2 times in platform."""
    platform_df, _, _ = data
    count = (platform_df["txn_id"] == "DUP123").sum()
    assert count == 2, f"Expected DUP123 to appear 2 times in platform, got {count}"


def test_bank_has_single_dup123(data):
    """Bank should have only 1 occurrence of DUP123."""
    _, bank_df, _ = data
    count = (bank_df["txn_id"] == "DUP123").sum()
    assert count == 1, f"Expected 1 DUP123 in bank, got {count}"


# ─────────────────────────────────────────────────────────────────
# GAP 4: Orphan refund REF456
# ─────────────────────────────────────────────────────────────────

def test_orphan_ref456_detected(data):
    """REF456 must appear in orphan_bank (bank only, no platform match)."""
    _, _, results = data
    orph = results["orphan_bank"]
    assert not orph.empty, "orphan_bank DataFrame should not be empty"
    orphan_ids = orph["txn_id"].tolist()
    assert "REF456" in orphan_ids, f"REF456 not found in orphans: {orphan_ids}"


def test_orphan_ref456_amount(data):
    """REF456 should be a -$50.00 refund."""
    _, _, results = data
    orph = results["orphan_bank"]
    ref_row = orph[orph["txn_id"] == "REF456"]
    assert not ref_row.empty, "REF456 row missing"
    assert float(ref_row["amount"].iloc[0]) == -50.00, \
        f"Expected -50.00, got {ref_row['amount'].iloc[0]}"


def test_ref456_not_in_platform(data):
    """REF456 must NOT exist in platform data."""
    platform_df, _, _ = data
    count = (platform_df["txn_id"] == "REF456").sum()
    assert count == 0, f"REF456 should not be in platform, found {count} rows"


# ─────────────────────────────────────────────────────────────────
# GENERAL INTEGRITY
# ─────────────────────────────────────────────────────────────────

def test_platform_has_expected_rows(data):
    """Platform should have ~100+ rows (90 base + 6 special)."""
    platform_df, _, _ = data
    assert len(platform_df) >= 96, f"Expected >= 96 platform rows, got {len(platform_df)}"


def test_bank_has_expected_rows(data):
    """Bank should have ~95+ rows (deduped DUP123 + REF456)."""
    _, bank_df, _ = data
    assert len(bank_df) >= 90, f"Expected >= 90 bank rows, got {len(bank_df)}"


def test_summary_total_gap_nonzero(data):
    """Platform and bank December totals should differ (rounding + cross-month)."""
    _, _, results = data
    s = results["summary"]
    assert s["platform_total"] != s["bank_total"], \
        "Platform and bank totals should differ due to planted gaps"


def test_total_issues_count(data):
    """Should detect at least 4 distinct issue categories."""
    _, _, results = data
    s = results["summary"]
    issue_flags = [
        s["duplicate_ids"] > 0,
        s["cross_month_count"] > 0,
        s["amount_mismatch_count"] > 0,
        s["orphan_count"] > 0,
    ]
    assert all(issue_flags), f"Not all 4 gap types detected. Flags: {issue_flags}"


# ─────────────────────────────────────────────────────────────────
# RUNNER
# ─────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    result = pytest.main([__file__, "-v", "--tb=short"])
    if result == 0:
        print("\n" + "=" * 50)
        print("✅  ALL TESTS PASS")
        print("=" * 50)
    else:
        print("\n❌  SOME TESTS FAILED — see output above")
        sys.exit(1)
