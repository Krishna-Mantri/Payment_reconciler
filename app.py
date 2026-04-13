"""
Payments Reconciliation Dashboard
A production-grade Streamlit app to find gaps between platform transactions
and bank settlements.

Run: streamlit run app.py
"""

import io
import random
import string
from datetime import date, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ─────────────────────────────────────────────────────────────────
# PAGE CONFIG
# ─────────────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Payments Reconciliation",
    page_icon="🏦",
    layout="wide",
    initial_sidebar_state="expanded",
)

# ─────────────────────────────────────────────────────────────────
# CUSTOM CSS
# ─────────────────────────────────────────────────────────────────
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;600&family=IBM+Plex+Sans:wght@300;400;600;700&display=swap');

html, body, [class*="css"] {
    font-family: 'IBM Plex Sans', sans-serif;
}
.main { background: #0d1117; }
h1, h2, h3 { font-family: 'IBM Plex Mono', monospace; }

.metric-card {
    background: #161b22;
    border: 1px solid #30363d;
    border-radius: 8px;
    padding: 20px;
    text-align: center;
}
.metric-value {
    font-family: 'IBM Plex Mono', monospace;
    font-size: 2rem;
    font-weight: 600;
    color: #58a6ff;
}
.metric-label {
    font-size: 0.8rem;
    color: #8b949e;
    text-transform: uppercase;
    letter-spacing: 0.1em;
    margin-top: 4px;
}
.metric-delta-neg { color: #f85149; }
.metric-delta-pos { color: #3fb950; }

.assumption-box {
    background: #161b22;
    border-left: 3px solid #58a6ff;
    border-radius: 0 8px 8px 0;
    padding: 16px 20px;
    margin: 8px 0;
    font-family: 'IBM Plex Mono', monospace;
    font-size: 0.82rem;
    color: #c9d1d9;
}
.gap-badge {
    display: inline-block;
    padding: 2px 10px;
    border-radius: 12px;
    font-size: 0.75rem;
    font-weight: 600;
    font-family: 'IBM Plex Mono', monospace;
}
.badge-red { background: #3d1f1f; color: #f85149; border: 1px solid #f85149; }
.badge-yellow { background: #2d2a1f; color: #d29922; border: 1px solid #d29922; }
.badge-blue { background: #1f2d3d; color: #58a6ff; border: 1px solid #58a6ff; }
.badge-green { background: #1f3d2d; color: #3fb950; border: 1px solid #3fb950; }
</style>
""", unsafe_allow_html=True)

# ─────────────────────────────────────────────────────────────────
# SYNTHETIC DATA GENERATION
# ─────────────────────────────────────────────────────────────────

def generate_synthetic_data() -> tuple[pd.DataFrame, pd.DataFrame]:
    """Generate realistic Dec-2024 platform + bank data with planted gaps."""
    random.seed(42)

    def rand_customer():
        return "CUST" + "".join(random.choices(string.digits, k=5))

    def rand_txn_id():
        return "TXN" + "".join(random.choices(string.ascii_uppercase + string.digits, k=8))

    # ── base transactions (90 normal) ──────────────────────────────
    base_rows = []
    dec_dates = [date(2024, 12, d) for d in range(1, 30)]  # Dec 1-29

    for _ in range(90):
        txn_date = random.choice(dec_dates)
        amount = round(random.uniform(-200, 2000), 2)
        base_rows.append({
            "txn_id": rand_txn_id(),
            "amount": amount,
            "txn_date": txn_date,
            "customer_id": rand_customer(),
        })

    # ── GAP 1: Cross-month – Dec 31 txn settles Jan 2, 2025 ────────
    cross_month_id = rand_txn_id()
    base_rows.append({
        "txn_id": cross_month_id,
        "amount": 375.00,
        "txn_date": date(2024, 12, 31),
        "customer_id": rand_customer(),
    })

    # ── GAP 2: Rounding – 3 txns platform has cents, bank rounds ───
    rounding_ids = [rand_txn_id() for _ in range(3)]
    rounding_amounts = [10.01, 10.99, 25.50]  # bank will floor to int
    for rid, amt in zip(rounding_ids, rounding_amounts):
        txn_date = random.choice(dec_dates)
        base_rows.append({
            "txn_id": rid,
            "amount": amt,
            "txn_date": txn_date,
            "customer_id": rand_customer(),
        })

    # ── GAP 3: Duplicate – DUP123 appears twice in platform ────────
    dup_date = date(2024, 12, 15)
    base_rows.append({"txn_id": "DUP123", "amount": 150.00, "txn_date": dup_date, "customer_id": "CUST99001"})
    base_rows.append({"txn_id": "DUP123", "amount": 150.00, "txn_date": dup_date, "customer_id": "CUST99001"})

    # ── GAP 4: Orphan refund REF456 in bank only ──────────────────
    # (added to bank below; NOT in platform)

    # Build platform DataFrame
    platform_df = pd.DataFrame(base_rows)
    platform_df["txn_date"] = pd.to_datetime(platform_df["txn_date"])

    # ── Build bank DataFrame ──────────────────────────────────────
    bank_rows = []

    for _, row in platform_df.iterrows():
        txn_id = row["txn_id"]
        amount = row["amount"]
        txn_date = row["txn_date"].date()

        # Skip DUP123 second occurrence (bank sees only 1)
        # We track if DUP123 already added
        if txn_id == "DUP123" and any(b["txn_id"] == "DUP123" for b in bank_rows):
            continue

        # Settlement date: +1 or +2 days (cross-month gets +2)
        if txn_id == cross_month_id:
            settle = date(2025, 1, 2)
        else:
            settle = txn_date + timedelta(days=random.choice([1, 2]))

        # Rounding: bank floors to int
        if txn_id in rounding_ids:
            bank_amount = float(int(amount))  # floor
        else:
            bank_amount = amount

        bank_rows.append({
            "txn_id": txn_id,
            "amount": bank_amount,
            "settle_date": settle,
            "customer_id": row["customer_id"],
        })

    # Add orphan refund REF456 (no platform match)
    bank_rows.append({
        "txn_id": "REF456",
        "amount": -50.00,
        "settle_date": date(2024, 12, 20),
        "customer_id": "CUST77777",
    })

    bank_df = pd.DataFrame(bank_rows)
    bank_df["settle_date"] = pd.to_datetime(bank_df["settle_date"])

    return platform_df, bank_df


# ─────────────────────────────────────────────────────────────────
# RECONCILIATION ENGINE
# ─────────────────────────────────────────────────────────────────

def run_reconciliation(platform: pd.DataFrame, bank: pd.DataFrame) -> dict:
    """
    Core reconciliation logic.
    Returns a dict with all gap analysis results.
    """
    results = {}

    # ── Normalise columns ────────────────────────────────────────
    platform = platform.copy()
    bank = bank.copy()
    platform["txn_date"] = pd.to_datetime(platform["txn_date"])
    bank["settle_date"] = pd.to_datetime(bank["settle_date"])
    platform["amount"] = platform["amount"].astype(float).round(2)
    bank["amount"] = bank["amount"].astype(float).round(2)

    # ── 1. DUPLICATES in platform ─────────────────────────────────
    dup_counts = platform.groupby("txn_id").size().reset_index(name="count")
    duplicates = dup_counts[dup_counts["count"] > 1].merge(
        platform.drop_duplicates("txn_id")[["txn_id", "amount", "txn_date", "customer_id"]],
        on="txn_id"
    )
    results["duplicates"] = duplicates

    # ── 2. MATCHING: join platform ↔ bank on txn_id ───────────────
    # Use first occurrence per txn_id in platform for matching
    platform_dedup = platform.drop_duplicates("txn_id", keep="first")

    merged = platform_dedup.merge(bank, on="txn_id", how="outer", suffixes=("_plat", "_bank"))

    # Matched rows (txn_id exists in both)
    matched = merged.dropna(subset=["txn_date", "settle_date"]).copy()
    matched["settle_lag_days"] = (
        matched["settle_date"] - matched["txn_date"]
    ).dt.days

    # ── 3. CROSS-MONTH: settled outside Dec 2024 ─────────────────
    cross_month = matched[
        (matched["txn_date"].dt.month == 12) &
        (matched["txn_date"].dt.year == 2024) &
        (matched["settle_date"].dt.month != 12)
    ].copy()
    results["cross_month"] = cross_month[
        ["txn_id", "amount_plat", "txn_date", "settle_date", "settle_lag_days"]
    ].rename(columns={"amount_plat": "amount"})

    # ── 4. AMOUNT MISMATCHES (rounding gaps) ─────────────────────
    matched["amount_diff"] = (matched["amount_plat"] - matched["amount_bank"]).round(4)
    amount_mismatches = matched[matched["amount_diff"].abs() > 0.001].copy()
    results["amount_mismatches"] = amount_mismatches[
        ["txn_id", "amount_plat", "amount_bank", "amount_diff", "txn_date", "settle_date"]
    ]

    # ── 5. ORPHANS: in bank but NOT in platform (refunds etc) ─────
    orphan_bank = merged[merged["txn_date"].isna()].copy()
    results["orphan_bank"] = orphan_bank[
        ["txn_id", "amount_bank", "settle_date", "customer_id_bank"]
    ].rename(columns={"amount_bank": "amount", "customer_id_bank": "customer_id"})

    # ── 6. MISSING SETTLEMENTS: in platform but NOT in bank ───────
    missing_settle = merged[merged["settle_date"].isna()].copy()
    results["missing_settlements"] = missing_settle[
        ["txn_id", "amount_plat", "txn_date", "customer_id_plat"]
    ].rename(columns={"amount_plat": "amount", "customer_id_plat": "customer_id"})

    # ── 7. LATE SETTLEMENTS (>3 day window) ───────────────────────
    late = matched[matched["settle_lag_days"].abs() > 3].copy()
    results["late_settlements"] = late[
        ["txn_id", "amount_plat", "txn_date", "settle_date", "settle_lag_days"]
    ].rename(columns={"amount_plat": "amount"})

    # ── 8. SUMMARY TOTALS ─────────────────────────────────────────
    plat_dec = platform[
        (platform["txn_date"].dt.month == 12) &
        (platform["txn_date"].dt.year == 2024)
    ]
    bank_dec = bank[
        (bank["settle_date"].dt.month == 12) &
        (bank["settle_date"].dt.year == 2024)
    ]

    results["summary"] = {
        "platform_total": round(plat_dec["amount"].sum(), 2),
        "bank_total": round(bank_dec["amount"].sum(), 2),
        "platform_count": len(platform),
        "bank_count": len(bank),
        "matched_count": len(matched),
        "duplicate_ids": len(duplicates),
        "cross_month_count": len(cross_month),
        "amount_mismatch_count": len(amount_mismatches),
        "orphan_count": len(orphan_bank),
        "missing_settle_count": len(missing_settle),
        "total_rounding_gap": round(amount_mismatches["amount_diff"].sum(), 4),
    }

    results["matched"] = matched

    return results


# ─────────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────────

def df_to_csv_bytes(df: pd.DataFrame) -> bytes:
    return df.to_csv(index=False).encode("utf-8")


def build_gaps_export(results: dict) -> pd.DataFrame:
    """Consolidate all gaps into one export DataFrame."""
    frames = []

    def tag(df, gap_type):
        d = df.copy()
        d["gap_type"] = gap_type
        return d

    if not results["cross_month"].empty:
        frames.append(tag(results["cross_month"], "CROSS_MONTH"))
    if not results["amount_mismatches"].empty:
        frames.append(tag(results["amount_mismatches"], "AMOUNT_MISMATCH"))
    if not results["duplicates"].empty:
        frames.append(tag(results["duplicates"], "DUPLICATE_PLATFORM"))
    if not results["orphan_bank"].empty:
        frames.append(tag(results["orphan_bank"], "ORPHAN_BANK"))
    if not results["missing_settlements"].empty:
        frames.append(tag(results["missing_settlements"], "MISSING_SETTLEMENT"))
    if not results["late_settlements"].empty:
        frames.append(tag(results["late_settlements"], "LATE_SETTLEMENT"))

    if frames:
        return pd.concat(frames, ignore_index=True)
    return pd.DataFrame(columns=["txn_id", "gap_type"])


ASSUMPTIONS = [
    "txn_id is the unique transaction key; any duplicate in the same source file is flagged as a data error.",
    "All monetary amounts are in USD; all dates and timestamps are UTC.",
    "A platform transaction is considered matched if a bank settlement with the same txn_id exists within a ±3-day window.",
    "Negative amounts represent refunds or reversals; processing fees are excluded from reconciliation.",
    "Bank amounts may be rounded (floor) to the nearest integer; residual cents are captured as rounding gaps.",
    "Transactions from Dec 31 settling in Jan 2025 are flagged as cross-month mismatches for month-end close.",
    "Bank records without a corresponding platform entry are treated as orphan/unmatched credits (potential refunds or errors).",
]

CAVEATS = [
    "🔴  **Scale**: This solution loads full datasets into RAM. For millions of transactions, replace Pandas with Apache Spark or DuckDB and use partitioned Parquet files on object storage.",
    "🟡  **Fraud Detection**: Reconciliation gaps here are accounting discrepancies only. Fraudulent transactions that balance numerically will not be flagged — a dedicated fraud-scoring model is required.",
    "🟠  **ID Cleanliness**: The engine assumes txn_ids have been normalised (trimmed, uppercased). Dirty or inconsistently formatted IDs from legacy systems will cause false-positive mismatches.",
]


# ─────────────────────────────────────────────────────────────────
# SIDEBAR
# ─────────────────────────────────────────────────────────────────

def sidebar():
    st.sidebar.markdown("""
    <div style="font-family:'IBM Plex Mono',monospace; font-size:1.1rem; font-weight:600; color:#58a6ff; margin-bottom:4px;">
    🏦 RECON ENGINE
    </div>
    <div style="font-size:0.75rem; color:#8b949e; margin-bottom:20px;">December 2024 · USD · UTC</div>
    """, unsafe_allow_html=True)

    data_source = st.sidebar.radio(
        "Data Source",
        ["Use generated synthetic data", "Upload my own CSVs"],
        index=0,
    )

    platform_df, bank_df = None, None

    if data_source == "Use generated synthetic data":
        st.sidebar.success("✓ Synthetic data loaded with 4 planted gaps")
        platform_df, bank_df = generate_synthetic_data()
    else:
        st.sidebar.markdown("**Platform CSV** (txn_id, amount, txn_date, customer_id)")
        p_file = st.sidebar.file_uploader("Platform transactions", type=["csv"], key="platform")
        st.sidebar.markdown("**Bank CSV** (txn_id, amount, settle_date, customer_id)")
        b_file = st.sidebar.file_uploader("Bank settlements", type=["csv"], key="bank")

        if p_file and b_file:
            try:
                platform_df = pd.read_csv(p_file)
                bank_df = pd.read_csv(b_file)
                st.sidebar.success(f"✓ Loaded {len(platform_df)} platform / {len(bank_df)} bank rows")
            except Exception as e:
                st.sidebar.error(f"Parse error: {e}")
        else:
            st.sidebar.info("Upload both CSVs to proceed")

    st.sidebar.markdown("---")
    st.sidebar.markdown("""
    <div style="font-size:0.7rem; color:#8b949e;">
    <b>Match window:</b> ±3 days<br>
    <b>Engine:</b> Pandas merge + gap rules<br>
    <b>Charts:</b> Plotly
    </div>
    """, unsafe_allow_html=True)

    return platform_df, bank_df


# ─────────────────────────────────────────────────────────────────
# UI COMPONENTS
# ─────────────────────────────────────────────────────────────────

def render_metric(label, value, delta=None, delta_is_bad=True):
    delta_html = ""
    if delta is not None:
        cls = "metric-delta-neg" if delta_is_bad else "metric-delta-pos"
        delta_html = f'<div class="{cls}" style="font-size:0.85rem;margin-top:4px;">{delta}</div>'
    st.markdown(f"""
    <div class="metric-card">
        <div class="metric-value">{value}</div>
        <div class="metric-label">{label}</div>
        {delta_html}
    </div>""", unsafe_allow_html=True)


def plotly_dark_layout(fig, title=""):
    fig.update_layout(
        title=title,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="#0d1117",
        font=dict(family="IBM Plex Mono", color="#c9d1d9", size=11),
        title_font=dict(family="IBM Plex Mono", size=13, color="#58a6ff"),
        xaxis=dict(gridcolor="#21262d", linecolor="#30363d"),
        yaxis=dict(gridcolor="#21262d", linecolor="#30363d"),
        legend=dict(bgcolor="rgba(0,0,0,0)"),
        margin=dict(l=20, r=20, t=40, b=20),
    )
    return fig


# ─────────────────────────────────────────────────────────────────
# MAIN APP
# ─────────────────────────────────────────────────────────────────

def main():
    # Header
    st.markdown("""
    <h1 style="font-family:'IBM Plex Mono',monospace; color:#58a6ff; font-size:1.8rem; margin-bottom:0;">
    ⚡ PAYMENTS RECONCILIATION DASHBOARD
    </h1>
    <p style="color:#8b949e; font-size:0.88rem; margin-top:4px;">
    Platform Transactions ↔ Bank Settlements · Month-End Gap Analysis · December 2024
    </p>
    <hr style="border-color:#21262d; margin:16px 0;">
    """, unsafe_allow_html=True)

    platform_df, bank_df = sidebar()

    if platform_df is None or bank_df is None:
        st.info("👈  Select a data source in the sidebar to begin reconciliation.")
        return

    # Run engine
    with st.spinner("Running reconciliation engine…"):
        results = run_reconciliation(platform_df, bank_df)

    s = results["summary"]
    net_gap = round(s["platform_total"] - s["bank_total"], 2)
    total_issues = (
        s["duplicate_ids"]
        + s["cross_month_count"]
        + s["amount_mismatch_count"]
        + s["orphan_count"]
        + s["missing_settle_count"]
    )

    # ── KPI Row ───────────────────────────────────────────────────
    st.markdown("### 📊 Summary Metrics")
    c1, c2, c3, c4, c5, c6 = st.columns(6)
    with c1: render_metric("Platform Total", f"${s['platform_total']:,.2f}")
    with c2: render_metric("Bank Total (Dec)", f"${s['bank_total']:,.2f}")
    with c3: render_metric("Net Gap", f"${net_gap:,.2f}", delta="⚠ Month-end diff" if net_gap != 0 else None)
    with c4: render_metric("Total Issues", str(total_issues), delta=f"{total_issues} flagged")
    with c5: render_metric("Matched Txns", str(s["matched_count"]), delta_is_bad=False)
    with c6: render_metric("Rounding Gap", f"${s['total_rounding_gap']:,.4f}", delta="cents lost" if s['total_rounding_gap'] != 0 else None)

    st.markdown("<br>", unsafe_allow_html=True)

    # ── Tabs ──────────────────────────────────────────────────────
    tabs = st.tabs([
        "🔴 All Gaps",
        "📅 Cross-Month",
        "💲 Rounding",
        "♊ Duplicates",
        "👻 Orphans",
        "📈 Charts",
        "📋 Assumptions",
        "⬇️ Export",
    ])

    # ── TAB: ALL GAPS ─────────────────────────────────────────────
    with tabs[0]:
        st.markdown("#### All Detected Gaps")
        gaps_df = build_gaps_export(results)
        if gaps_df.empty:
            st.success("✅ No gaps detected!")
        else:
            gap_summary = gaps_df.groupby("gap_type").size().reset_index(name="count")
            st.dataframe(
                gap_summary.style.set_properties(**{"background-color": "#161b22", "color": "#c9d1d9"}),
                use_container_width=True,
                hide_index=True,
            )
            st.markdown(f"**Total gap rows:** {len(gaps_df)}")
            st.dataframe(gaps_df, use_container_width=True, hide_index=True)

    # ── TAB: CROSS-MONTH ─────────────────────────────────────────
    with tabs[1]:
        st.markdown("#### Cross-Month Settlements")
        st.markdown("""
        <div class="assumption-box">
        Transactions posted in December 2024 but settled in January 2025+ are excluded from
        December bank totals, causing month-end imbalance.
        </div>
        """, unsafe_allow_html=True)
        cm = results["cross_month"]
        if cm.empty:
            st.success("No cross-month mismatches found.")
        else:
            st.error(f"⚠️ {len(cm)} cross-month transaction(s) found")
            st.dataframe(cm, use_container_width=True, hide_index=True)
            st.markdown(f"**Total cross-month amount:** ${cm['amount'].sum():,.2f}")

    # ── TAB: ROUNDING ────────────────────────────────────────────
    with tabs[2]:
        st.markdown("#### Amount / Rounding Mismatches")
        st.markdown("""
        <div class="assumption-box">
        Bank may floor/round cent values. Platform records exact amounts.
        Each row below shows platform_amount - bank_amount = gap.
        </div>
        """, unsafe_allow_html=True)
        am = results["amount_mismatches"]
        if am.empty:
            st.success("No amount mismatches.")
        else:
            st.warning(f"💲 {len(am)} rounding mismatch(es) | Total gap: ${am['amount_diff'].sum():,.4f}")
            st.dataframe(am, use_container_width=True, hide_index=True)

    # ── TAB: DUPLICATES ──────────────────────────────────────────
    with tabs[3]:
        st.markdown("#### Duplicate Transaction IDs (Platform)")
        st.markdown("""
        <div class="assumption-box">
        txn_id must be unique. Duplicates in the platform feed indicate double-posting errors
        and will cause over-reconciliation if not corrected upstream.
        </div>
        """, unsafe_allow_html=True)
        dups = results["duplicates"]
        if dups.empty:
            st.success("No duplicates found.")
        else:
            st.error(f"♊ {len(dups)} duplicate ID(s) detected")
            st.dataframe(dups, use_container_width=True, hide_index=True)

    # ── TAB: ORPHANS ─────────────────────────────────────────────
    with tabs[4]:
        st.markdown("#### Orphan Bank Entries (No Platform Match)")
        st.markdown("""
        <div class="assumption-box">
        Bank records with no matching platform transaction. Typically refunds, bank adjustments,
        or fraudulent charges posted directly at the bank level.
        </div>
        """, unsafe_allow_html=True)
        orph = results["orphan_bank"]
        if orph.empty:
            st.success("No orphan bank entries.")
        else:
            st.error(f"👻 {len(orph)} orphan bank record(s)")
            st.dataframe(orph, use_container_width=True, hide_index=True)

        st.markdown("#### Missing Settlements (Platform → No Bank)")
        ms = results["missing_settlements"]
        if ms.empty:
            st.success("All platform transactions have a bank settlement.")
        else:
            st.warning(f"⏳ {len(ms)} platform txn(s) with no bank settlement")
            st.dataframe(ms, use_container_width=True, hide_index=True)

    # ── TAB: CHARTS ──────────────────────────────────────────────
    with tabs[5]:
        st.markdown("#### Visual Analysis")

        col1, col2 = st.columns(2)

        with col1:
            # Gap type breakdown
            gaps_df = build_gaps_export(results)
            if not gaps_df.empty:
                gap_counts = gaps_df.groupby("gap_type").size().reset_index(name="count")
                fig = px.bar(
                    gap_counts, x="gap_type", y="count",
                    color="gap_type",
                    color_discrete_sequence=["#f85149", "#d29922", "#58a6ff", "#3fb950", "#a371f7", "#ff7b72"],
                    labels={"gap_type": "Gap Type", "count": "# Occurrences"},
                )
                plotly_dark_layout(fig, "Gap Types Breakdown")
                st.plotly_chart(fig, use_container_width=True)

        with col2:
            # Settlement lag distribution
            matched = results["matched"]
            if not matched.empty:
                fig2 = px.histogram(
                    matched[matched["settle_lag_days"].between(-10, 30)],
                    x="settle_lag_days",
                    nbins=20,
                    color_discrete_sequence=["#58a6ff"],
                    labels={"settle_lag_days": "Settle Lag (days)", "count": "# Transactions"},
                )
                plotly_dark_layout(fig2, "Settlement Lag Distribution")
                fig2.add_vline(x=3, line_dash="dash", line_color="#d29922",
                               annotation_text="3-day window", annotation_font_color="#d29922")
                fig2.add_vline(x=0, line_dash="dash", line_color="#3fb950",
                               annotation_text="Same day", annotation_font_color="#3fb950")
                st.plotly_chart(fig2, use_container_width=True)

        col3, col4 = st.columns(2)

        with col3:
            # Platform vs Bank totals gauge
            plat_t = abs(s["platform_total"])
            bank_t = abs(s["bank_total"])
            fig3 = go.Figure()
            fig3.add_trace(go.Bar(name="Platform", x=["Dec 2024"], y=[plat_t],
                                   marker_color="#58a6ff"))
            fig3.add_trace(go.Bar(name="Bank", x=["Dec 2024"], y=[bank_t],
                                   marker_color="#3fb950"))
            plotly_dark_layout(fig3, "Platform vs Bank Totals (Dec 2024)")
            fig3.update_layout(barmode="group")
            st.plotly_chart(fig3, use_container_width=True)

        with col4:
            # Daily transaction volume
            platform_copy = platform_df.copy()
            platform_copy["txn_date"] = pd.to_datetime(platform_copy["txn_date"])
            daily = platform_copy.groupby(platform_copy["txn_date"].dt.date).agg(
                txn_count=("txn_id", "count"),
                volume=("amount", "sum")
            ).reset_index()
            fig4 = px.bar(daily, x="txn_date", y="txn_count",
                          color_discrete_sequence=["#a371f7"],
                          labels={"txn_date": "Date", "txn_count": "# Transactions"})
            plotly_dark_layout(fig4, "Daily Transaction Volume (Platform)")
            st.plotly_chart(fig4, use_container_width=True)

    # ── TAB: ASSUMPTIONS ─────────────────────────────────────────
    with tabs[6]:
        st.markdown("#### Reconciliation Assumptions")
        for i, a in enumerate(ASSUMPTIONS, 1):
            st.markdown(f'<div class="assumption-box">A{i}: {a}</div>', unsafe_allow_html=True)

        st.markdown("#### ⚠️ Production Caveats")
        for c in CAVEATS:
            st.markdown(c)

    # ── TAB: EXPORT ──────────────────────────────────────────────
    with tabs[7]:
        st.markdown("#### Export Reconciliation Artifacts")

        gaps_df = build_gaps_export(results)
        assumptions_log = pd.DataFrame({
            "assumption_id": [f"A{i}" for i in range(1, len(ASSUMPTIONS) + 1)],
            "description": ASSUMPTIONS,
        })

        col_a, col_b, col_c, col_d = st.columns(4)

        with col_a:
            st.download_button(
                "⬇️ Gaps Report (CSV)",
                data=df_to_csv_bytes(gaps_df),
                file_name="reconciliation_gaps_dec2024.csv",
                mime="text/csv",
            )
        with col_b:
            st.download_button(
                "⬇️ Assumptions Log (CSV)",
                data=df_to_csv_bytes(assumptions_log),
                file_name="reconciliation_assumptions.csv",
                mime="text/csv",
            )
        with col_c:
            st.download_button(
                "⬇️ Platform Data (CSV)",
                data=df_to_csv_bytes(platform_df),
                file_name="platform_transactions.csv",
                mime="text/csv",
            )
        with col_d:
            st.download_button(
                "⬇️ Bank Settlements (CSV)",
                data=df_to_csv_bytes(bank_df),
                file_name="bank_settlements.csv",
                mime="text/csv",
            )

        st.markdown("#### Full Matched Table")
        matched = results["matched"]
        st.dataframe(matched, use_container_width=True, hide_index=True)


if __name__ == "__main__":
    main()
