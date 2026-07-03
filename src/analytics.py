"""
analytics.py  —  Mindex Data Engineer / Data Architect Code Challenge (Part 4)

Answers the five business questions against the star-schema warehouse
(``output/warehouse.db``) and writes the combined results to
``output/analytics.json``.

Why SQL (via stdlib ``sqlite3``) rather than pandas
---------------------------------------------------
The data is already cleaned, conformed and modeled into a star schema (Part 3),
so every question here is a set-based aggregation over a fact table joined to its
dimensions — exactly what SQL expresses most directly. Querying the warehouse
also exercises the model the way a downstream analyst or BI tool would, keeps the
business logic declarative and auditable, and avoids re-deriving in pandas what
the database already indexes. Month-over-month *percentage* change and the
return-rate *flag* are computed in Python on top of the SQL aggregates, because
guarded division (avoiding divide-by-zero) and shaping nested output read more
clearly there.

Usage:
    python src/analytics.py         # or: python -m src.analytics
"""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from pathlib import Path

from src.loader import DB_PATH, OUTPUT_DIR

# A store is flagged for review when more than this share of its transactions
# are returns (Part 4, Q3).
RETURN_RATE_THRESHOLD = 0.10

# The "most recent 30-day window of data" (Part 4, Q1): the 30 calendar days
# ending on — and including — the latest transaction date in the warehouse.
REVENUE_WINDOW_DAYS = 30


def _connect(db_path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _max_transaction_date(conn: sqlite3.Connection) -> str:
    """Latest date present in the fact table, as an ISO ``YYYY-MM-DD`` string."""
    row = conn.execute(
        """
        SELECT MAX(d.date) AS max_date
        FROM fact_sales f
        JOIN dim_date d ON f.date_key = d.date_key
        """
    ).fetchone()
    return row["max_date"]


# ── Q1. Top 5 stores by net revenue (most recent 30-day window) ─────────────────

def top_stores_by_net_revenue(conn: sqlite3.Connection) -> dict:
    """Top 5 stores by net revenue over the trailing 30-day window.

    Net revenue = SUM(total_amount); returns carry negative amounts, so they
    reduce revenue rather than being filtered out.
    """
    max_date = _max_transaction_date(conn)
    cutoff = (
        datetime.strptime(max_date, "%Y-%m-%d")
        - timedelta(days=REVENUE_WINDOW_DAYS - 1)
    ).strftime("%Y-%m-%d")

    rows = conn.execute(
        """
        SELECT s.store_id, s.store_name, s.region,
               ROUND(SUM(f.total_amount), 2) AS net_revenue,
               COUNT(*)                       AS transaction_count
        FROM fact_sales f
        JOIN dim_store s ON f.store_key = s.store_key
        JOIN dim_date  d ON f.date_key  = d.date_key
        WHERE d.date BETWEEN ? AND ?
        GROUP BY s.store_key
        ORDER BY net_revenue DESC
        LIMIT 5
        """,
        (cutoff, max_date),
    ).fetchall()

    return {
        "window": {"start": cutoff, "end": max_date, "days": REVENUE_WINDOW_DAYS},
        "stores": [dict(r) for r in rows],
    }


# ── Q2. Month-over-month revenue change (%) by product category ─────────────────

def mom_revenue_change_by_category(conn: sqlite3.Connection) -> list[dict]:
    """Per-category monthly net revenue and month-over-month % change.

    ``mom_change_pct`` is null for a category's first month (no prior month) and
    for any month following one with zero revenue (undefined change).
    """
    rows = conn.execute(
        """
        SELECT p.category,
               substr(d.date, 1, 7)       AS month,
               ROUND(SUM(f.total_amount), 2) AS revenue
        FROM fact_sales f
        JOIN dim_product p ON f.product_key = p.product_key
        JOIN dim_date    d ON f.date_key    = d.date_key
        GROUP BY p.category, month
        ORDER BY p.category, month
        """
    ).fetchall()

    by_category: dict[str, list[dict]] = {}
    for r in rows:
        by_category.setdefault(r["category"], []).append(
            {"month": r["month"], "revenue": r["revenue"]}
        )

    result = []
    for category, months in by_category.items():
        prev = None
        series = []
        for m in months:
            change = None
            if prev is not None and prev != 0:
                change = round((m["revenue"] - prev) / prev * 100, 2)
            series.append({**m, "mom_change_pct": change})
            prev = m["revenue"]
        result.append({"category": category, "monthly": series})
    return result


# ── Q3. Return rate by store ────────────────────────────────────────────────────

def return_rate_by_store(conn: sqlite3.Connection) -> list[dict]:
    """Return rate (return txns / total txns) per store, with a >10% flag."""
    rows = conn.execute(
        """
        SELECT s.store_id, s.store_name,
               SUM(f.is_return) AS return_transactions,
               COUNT(*)         AS total_transactions
        FROM fact_sales f
        JOIN dim_store s ON f.store_key = s.store_key
        GROUP BY s.store_key
        ORDER BY s.store_id
        """
    ).fetchall()

    result = []
    for r in rows:
        rate = r["return_transactions"] / r["total_transactions"]
        result.append(
            {
                "store_id": r["store_id"],
                "store_name": r["store_name"],
                "return_transactions": r["return_transactions"],
                "total_transactions": r["total_transactions"],
                "return_rate": round(rate, 4),
                "high_return_rate": rate > RETURN_RATE_THRESHOLD,
            }
        )
    return result


# ── Q4. Average transaction value by region (excluding returns) ─────────────────

def avg_transaction_value_by_region(conn: sqlite3.Connection) -> list[dict]:
    """Average transaction value per region, excluding return transactions."""
    rows = conn.execute(
        """
        SELECT s.region,
               ROUND(AVG(f.total_amount), 2) AS avg_transaction_value,
               COUNT(*)                       AS transaction_count
        FROM fact_sales f
        JOIN dim_store s ON f.store_key = s.store_key
        WHERE f.is_return = 0
        GROUP BY s.region
        ORDER BY avg_transaction_value DESC
        """
    ).fetchall()
    return [dict(r) for r in rows]


# ── Q5. Top 10 customers by lifetime spend (excluding guests) ───────────────────

def top_customers_by_lifetime_spend(conn: sqlite3.Connection) -> list[dict]:
    """Top 10 identified customers by net lifetime spend.

    Guest/anonymous transactions (``is_guest = 1``, NULL ``customer_id``) are
    excluded. Lifetime spend is net of the customer's returns; average order
    value = lifetime spend / transaction count.
    """
    rows = conn.execute(
        """
        SELECT f.customer_id,
               ROUND(SUM(f.total_amount), 2)              AS lifetime_spend,
               COUNT(*)                                   AS transaction_count,
               ROUND(SUM(f.total_amount) * 1.0 / COUNT(*), 2) AS avg_order_value
        FROM fact_sales f
        WHERE f.is_guest = 0
        GROUP BY f.customer_id
        ORDER BY lifetime_spend DESC
        LIMIT 10
        """
    ).fetchall()
    return [dict(r) for r in rows]


# ── Orchestration ────────────────────────────────────────────────────────────

def run_analytics(db_path: Path = DB_PATH) -> dict:
    """Run all five analyses and return the combined results dict."""
    conn = _connect(db_path)
    try:
        return {
            "top_5_stores_by_net_revenue_30d": top_stores_by_net_revenue(conn),
            "mom_revenue_change_by_category": mom_revenue_change_by_category(conn),
            "return_rate_by_store": return_rate_by_store(conn),
            "avg_transaction_value_by_region": avg_transaction_value_by_region(conn),
            "top_10_customers_by_lifetime_spend": top_customers_by_lifetime_spend(conn),
        }
    finally:
        conn.close()


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    results = run_analytics()

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "source": str(DB_PATH),
        "results": results,
    }
    out_path = OUTPUT_DIR / "analytics.json"
    with out_path.open("w") as f:
        json.dump(report, f, indent=2, default=str)

    # Console summary.
    top = results["top_5_stores_by_net_revenue_30d"]
    print(f"  Q1 top store ({top['window']['start']}→{top['window']['end']}): "
          f"{top['stores'][0]['store_name']} "
          f"(${top['stores'][0]['net_revenue']:,.2f})")
    flagged = [s["store_id"] for s in results["return_rate_by_store"]
               if s["high_return_rate"]]
    print(f"  Q3 stores over {int(RETURN_RATE_THRESHOLD * 100)}% return rate: "
          f"{flagged or 'none'}")
    print(f"  Q5 top customer: {results['top_10_customers_by_lifetime_spend'][0]['customer_id']} "
          f"(${results['top_10_customers_by_lifetime_spend'][0]['lifetime_spend']:,.2f})")
    print(f"\nAnalytics written to: {out_path}")


if __name__ == "__main__":
    main()
