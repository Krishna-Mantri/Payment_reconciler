# ⚡ Payments Reconciliation Dashboard

> A production-grade Streamlit app that detects gaps between instant payment records and T+1/T+2 bank settlements — cross-month mismatches, rounding errors, duplicates, and orphan refunds.

[![Tests](https://img.shields.io/badge/tests-17%2F17%20passing-brightgreen)](#test-suite)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue)](#quick-start)
[![Streamlit](https://img.shields.io/badge/streamlit-1.x-red)](#quick-start)
[![License](https://img.shields.io/badge/license-MIT-purple)](#license)

---

## The Problem

Payments platforms record transactions instantly; banks settle 1–2 days later. Month-end books don't balance — this tool finds exactly why.

---

## Quick Start

```bash
# 1. Install dependencies
pip install streamlit pandas plotly pytest

# 2. Launch the dashboard
streamlit run app.py

# 3. (Optional) Generate sample CSVs manually
python generate_csvs.py

# 4. Run the test suite
pytest test_reconciliation.py -v
```

> **No configuration required.** Select "Use generated synthetic data" in the sidebar to reconcile instantly.

---

## File Structure

```
payments-recon/
  ├── app.py                    # Streamlit dashboard + reconciliation engine
  ├── test_reconciliation.py    # 17 pytest unit tests
  ├── generate_csvs.py          # Standalone CSV generator
  ├── platform_transactions.csv # 96-row Dec 2024 platform data
  ├── bank_settlements.csv      # 96-row bank data (4 gaps planted)
  └── README.md
```

---

## Data Flow

```
Platform CSV ──┐
               ├──► Reconciliation Engine (Pandas outer join · ±3-day window) ──► Gap Report
Bank CSV ──────┘
```

Both CSVs feed the engine simultaneously via a Pandas outer merge keyed on `txn_id`.

**Platform schema:** `txn_id | amount | txn_date | customer_id`  
**Bank schema:** `txn_id | amount | settle_date | customer_id`

---

## The 4 Planted Gaps

| # | Gap Type | How It's Planted | How It's Detected |
|---|---|---|---|
| 1 | **Cross-month** | Dec 31 txn ($375) with `settle_date` = Jan 2, 2025 | `settle_date.month ≠ 12` while `txn_date.month == 12` |
| 2 | **Rounding** | 3 txns ($10.01, $10.99, $25.50) — bank floors to integer | `|amount_plat − amount_bank| > 0.001` |
| 3 | **Duplicate** | `DUP123` appears twice in platform, once in bank | `groupby(txn_id).count() > 1` in platform |
| 4 | **Orphan refund** | `REF456` −$50.00 in bank only, no platform entry | Outer join rows where platform side is `NaN` |

---

## App Features

| Feature | Detail |
|---|---|
| 📂 Dual data source | Load built-in synthetic data or upload your own CSVs via the sidebar |
| 🔗 Smart matching | Outer join on `txn_id` with configurable ±3-day settle window |
| 📈 Plotly charts | Gap-type bar chart · settlement lag histogram · daily volume |
| 📋 8 analysis tabs | All Gaps · Cross-Month · Rounding · Duplicates · Orphans · Charts · Assumptions · Export |
| ⬇️ CSV export | One-click downloads: gap report · assumptions log · raw platform · raw bank |
| 🌙 Dark-mode UI | IBM Plex Mono + Plex Sans · GitHub-dark color palette |

---

## Assumptions

| ID | Statement |
|---|---|
| A1 | `txn_id` is the unique transaction key — any duplicate within the same source file is flagged as a data error. |
| A2 | All monetary amounts are in USD. All dates and timestamps are UTC. |
| A3 | A platform transaction is considered matched if a bank settlement with the same `txn_id` exists within a ±3-day window. |
| A4 | Negative amounts represent refunds or reversals. Processing fees are excluded. |
| A5 | Bank amounts may be rounded (floored) to the nearest integer; residual cents are rounding gaps. |
| A6 | Transactions from Dec 31 settling in Jan 2025 are flagged as cross-month mismatches. |
| A7 | Bank records without a corresponding platform entry are orphan credits (potential refunds or errors). |

---

## Test Suite — 17 Tests, All Green

```
PASS  GAP1 — cross_month not empty
PASS  GAP1 — Dec-31 transaction present
PASS  GAP1 — settles in Jan-2025
PASS  GAP1 — amount is $375.00
PASS  GAP2 — rounding mismatches >= 3
PASS  GAP2 — platform total > bank total (rounding)
PASS  GAP2 — seeded amounts found in mismatches
PASS  GAP3 — duplicates table not empty
PASS  GAP3 — DUP123 in duplicates
PASS  GAP3 — platform count == 2
PASS  GAP3 — bank count == 1
PASS  GAP4 — orphans not empty
PASS  GAP4 — REF456 in orphans
PASS  GAP4 — REF456 amount == -$50.00
PASS  GAP4 — REF456 not in platform
PASS  ALL 4 issue categories detected
PASS  Platform total != Bank total

══════════════════════════════
  ALL TESTS PASS  (17/17)
══════════════════════════════
```

---

## ⚠️ Production Caveats

**🔴 Scale — Pandas has RAM limits**  
This solution loads full datasets into memory. For millions of transactions, replace Pandas with Apache Spark or DuckDB and use partitioned Parquet files on S3/GCS. The reconciliation logic maps 1:1 to SQL window functions.

**🟡 No fraud detection**  
Reconciliation gaps here are accounting discrepancies only. Fraudulent transactions that balance numerically will not be flagged — a dedicated fraud-scoring or anomaly-detection model is required.

**🟠 Assumes clean IDs**  
The engine assumes `txn_id` values are normalised (trimmed whitespace, consistent casing). Legacy core-banking systems often emit IDs with trailing spaces or mixed case — a pre-normalisation layer is essential at scale.

---

## Deploying to Streamlit Cloud

1. Push this repo to GitHub
2. Go to [share.streamlit.io](https://share.streamlit.io) and connect the repo
3. Set **Main file path** to `app.py`
4. Click **Deploy** — no secrets or environment variables required

---

## License

MIT — free to use, modify, and distribute.

---

*payments-reconciliation-dashboard · December 2024 · USD · UTC*
