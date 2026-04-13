"""
Generate and save sample CSVs for the reconciliation dashboard.
Run: python generate_csvs.py
"""
import sys
import os
sys.path.insert(0, os.path.dirname(__file__))

from app import generate_synthetic_data

platform_df, bank_df = generate_synthetic_data()

platform_df.to_csv("platform_transactions.csv", index=False)
bank_df.to_csv("bank_settlements.csv", index=False)

print(f"✅ platform_transactions.csv  — {len(platform_df)} rows")
print(f"✅ bank_settlements.csv       — {len(bank_df)} rows")
print()
print("Planted gaps:")
print(f"  GAP 1 (Cross-month): {len(platform_df[platform_df['txn_date'].astype(str).str.startswith('2024-12-31')])} Dec-31 txn(s)")
print(f"  GAP 2 (Rounding):    txns with $10.01, $10.99, $25.50")
print(f"  GAP 3 (Duplicate):   DUP123 appears {(platform_df['txn_id']=='DUP123').sum()} times in platform")
print(f"  GAP 4 (Orphan):      REF456 in bank only: {(bank_df['txn_id']=='REF456').sum()} row(s)")
