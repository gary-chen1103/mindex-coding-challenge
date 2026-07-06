"""
test_pipeline.py  —  Mindex Data Engineer Code Challenge (Part 5)

Tests across the three required areas:

  * Profiling      — known-input stats + edge cases (empty / all-null).
  * Cleaning       — specific transformations against hand-built inputs.
  * Analytics      — a small controlled fixture loaded into SQLite, with
                     known query results asserted.

Each test builds its own tiny, fully-known input so the expected values are
computed by hand rather than lifted from the real dataset.
"""

from __future__ import annotations

from datetime import date

import pandas as pd
import pytest

from src.profiler import profile
from src.cleaner import (
    CleanResult,
    clean_products,
    clean_stores,
    clean_transactions,
)
from src.loader import build_warehouse
from src.analytics import run_analytics


# ── Profiling ──────────────────────────────────────────────────────────────────

def test_profile_known_counts_types_and_stats():
    """profile() reports correct counts, null %, numeric stats and date stats.

    Columns are strings (as read_raw would produce) so profile() infers types
    itself. Rows 0 and 4 are identical → exactly one duplicate row.
    """
    df = pd.DataFrame(
        {
            "amount":     ["10", "0", "-5", "20", "10"],
            "order_date": ["2026-01-01", "2026-06-01", "2026-01-03", "2026-12-31", "2026-01-01"],
            "city":       ["NYC", None, "LA", "SF", "NYC"],
        }
    )

    rep = profile(df, "sample", today=date(2026, 2, 1))

    assert rep["row_count"] == 5
    assert rep["column_count"] == 3
    assert rep["duplicate_row_count"] == 1

    amount = rep["columns"]["amount"]
    assert amount["inferred_type"] == "numeric"
    assert amount["min"] == -5.0
    assert amount["max"] == 20.0
    assert amount["mean"] == 7.0          # (10 + 0 - 5 + 20 + 10) / 5
    assert amount["zero_count"] == 1
    assert amount["negative_count"] == 1

    order_date = rep["columns"]["order_date"]
    assert order_date["inferred_type"] == "date"
    assert order_date["min_date"] == "2026-01-01"
    assert order_date["max_date"] == "2026-12-31"
    # Relative to 2026-02-01, both 2026-06-01 and 2026-12-31 are in the future.
    assert order_date["future_date_count"] == 2

    city = rep["columns"]["city"]
    assert city["null_count"] == 1
    assert city["null_pct"] == 20.0


def test_profile_empty_dataframe():
    """Edge case: an empty DataFrame must not crash and reports zero counts."""
    rep = profile(pd.DataFrame(), "empty", today=date(2026, 1, 1))
    assert rep["row_count"] == 0
    assert rep["column_count"] == 0
    assert rep["duplicate_row_count"] == 0
    assert rep["columns"] == {}


def test_profile_all_null_column():
    """Edge case: an all-null column is 100% null and typed as string."""
    df = pd.DataFrame({"blank": [None, None, None]})
    rep = profile(df, "nulls", today=date(2026, 1, 1))
    col = rep["columns"]["blank"]
    assert col["null_count"] == 3
    assert col["null_pct"] == 100.0
    assert col["inferred_type"] == "string"
    # No numeric/date stats should be attached to a non-typed column.
    assert "min" not in col and "min_date" not in col


# ── Cleaning transformations ────────────────────────────────────────────────────

def test_clean_stores_pads_zip_dedups_and_imputes_region():
    raw = pd.DataFrame(
        {
            "store_id":    ["S1", "S2", "S2", "S3"],
            "store_name":  ["Alpha", "Beta", "Beta 2", "Gamma"],
            "city":        ["A", "B", "B", "C"],
            "state":       ["NY", "MN", "MN", "OR"],
            "zip_code":    ["0938", "55425", "55425", "97220"],   # S1 has a 4-digit zip
            "region":      ["Northeast", "Midwest", "Midwest", None],  # S3 null region
            "opened_date": ["2020-03-15", "2011-04-07", "2011-04-07", "2019-05-14"],
        }
    )

    clean, issues = clean_stores(raw)

    # 4-digit zip zero-padded to 5 chars, preserved as string (no data loss).
    assert clean.loc[clean.store_id == "S1", "zip_code"].iloc[0] == "00938"
    # Duplicate store_id dropped → one row per store.
    assert clean["store_id"].is_unique
    assert len(clean) == 3
    # Null region imputed.
    assert clean.loc[clean.store_id == "S3", "region"].iloc[0] == "Unknown"
    # opened_date standardized to ISO date strings.
    assert clean.loc[clean.store_id == "S1", "opened_date"].iloc[0] == "2020-03-15"

    kinds = {i["issue"] for i in issues}
    assert any("zip" in k.lower() for k in kinds)
    assert any("region" in k.lower() for k in kinds)


def test_clean_products_keeps_highest_price_and_flags_zero():
    raw = pd.DataFrame(
        {
            "product_id":   ["P1", "P1", "P2", "P3"],
            "product_name": ["one", "one", "two", "three"],
            "category":     ["Cat", "Cat", None, "Cat"],   # P2 null category
            "unit_price":   ["10.00", "18.50", "5.00", "0.00"],  # P1 two prices; P3 zero
            "supplier_id":  ["SUP1", "SUP1", "SUP2", "SUP3"],
        }
    )

    clean, _ = clean_products(raw)

    assert clean["product_id"].is_unique
    # Two prices on record for P1 → keep the higher one as catalog price.
    assert clean.loc[clean.product_id == "P1", "unit_price"].iloc[0] == 18.50
    # Null category imputed.
    assert clean.loc[clean.product_id == "P2", "category"].iloc[0] == "Unknown"
    # Zero price kept but flagged invalid; valid prices flagged True.
    assert bool(clean.loc[clean.product_id == "P3", "price_valid"].iloc[0]) is False
    assert bool(clean.loc[clean.product_id == "P1", "price_valid"].iloc[0]) is True


def test_clean_transactions_parses_flags_and_excludes():
    raw = pd.DataFrame(
        {
            "transaction_id":   ["X1", "X2", "X3", "X4", "X5", "X6", "X7"],
            "transaction_date": ["2026-05-01", "2026-05-02", "2026-05-03",
                                  "2026-05-04", "2026-05-05", "2026-07-01", "2026-05-06"],
            "store_id":         ["S1", "S1", "S1", "S9", "S1", "S1", "S1"],   # X4 orphan store
            "product_id":       ["P1", "P1", "P1", "P1", "P1", "P1", "P1"],
            "customer_id":      ["C1", None, "C2", "C1", "C1", "C1", "C1"],   # X2 guest
            "quantity":         ["2", "1", "-1", "1", "0", "1", "1"],         # X3 return, X5 zero-qty
            "unit_price":       ["10", "10", "10", "10", "10", "10", "10"],
            "total_amount":     ["20", "$10.00", "-10", "10", "0", "10", "15"],  # X2 currency, X7 mismatch
        }
    )

    clean, issues = clean_transactions(
        raw,
        valid_store_ids={"S1"},
        valid_product_ids={"P1"},
        as_of_date=date(2026, 6, 1),
    )

    surviving = set(clean["transaction_id"])
    # Excluded: X4 (orphan store), X5 (zero qty), X6 (future date).
    assert surviving == {"X1", "X2", "X3", "X7"}

    # Currency string parsed to a real float.
    x2 = clean.loc[clean.transaction_id == "X2", "total_amount"].iloc[0]
    assert x2 == 10.0
    assert clean["total_amount"].dtype.kind == "f"

    # Flags computed on the surviving set.
    assert int(clean["is_return"].sum()) == 1     # X3
    assert int(clean["is_guest"].sum()) == 1      # X2
    assert int(clean["price_mismatch"].sum()) == 1  # X7 (15 != 1 * 10)

    # Exclusions were logged as issues.
    logged = {i["issue"] for i in issues}
    assert any("Orphaned store" in k for k in logged)
    assert any("Zero-quantity" in k for k in logged)
    assert any("Future-dated" in k for k in logged)


# ── Analytics (controlled SQLite fixture) ───────────────────────────────────────

@pytest.fixture
def warehouse(tmp_path):
    """Build a tiny warehouse from a hand-built, already-cleaned CleanResult.

    Layout (all dated the same day so the 30-day window covers everything):
        Store S1 (East): C1 buys (qty2,$20), buys (qty1,$10), returns (qty-1,-$10)
        Store S2 (West): guest buys (qty1,$50)
    """
    ts = pd.Timestamp("2026-06-01")
    stores = pd.DataFrame(
        {
            "store_id": ["S1", "S2"],
            "store_name": ["Alpha", "Beta"],
            "city": ["A", "B"],
            "state": ["NY", "CA"],
            "zip_code": ["10001", "90001"],
            "region": ["East", "West"],
            "opened_date": ["2020-01-01", "2021-01-01"],
        }
    )
    products = pd.DataFrame(
        {
            "product_id": ["P1", "P2"],
            "product_name": ["one", "two"],
            "category": ["Cat1", "Cat2"],
            "unit_price": [10.0, 50.0],
            "supplier_id": ["SUP1", "SUP2"],
            "price_valid": [True, True],
        }
    )
    transactions = pd.DataFrame(
        {
            "transaction_id": ["T1", "T2", "T3", "T4"],
            "transaction_date": [ts, ts, ts, ts],
            "store_id": ["S1", "S1", "S1", "S2"],
            "product_id": ["P1", "P1", "P1", "P2"],
            "customer_id": ["C1", "C1", "C1", None],
            "quantity": pd.array([2, 1, -1, 1], dtype="Int64"),
            "unit_price": [10.0, 10.0, 10.0, 50.0],
            "total_amount": [20.0, 10.0, -10.0, 50.0],
            "is_return": [False, False, True, False],
            "is_guest": [False, False, False, True],
            "price_mismatch": [False, False, False, False],
        }
    )
    clean = CleanResult(stores=stores, products=products, transactions=transactions)

    db_path = tmp_path / "test_warehouse.db"
    summary = build_warehouse(db_path=db_path, clean=clean)
    assert summary["fact_sales"] == 4
    return db_path


def test_analytics_on_controlled_fixture(warehouse):
    results = run_analytics(warehouse)

    # Return rate by store: S1 has 1 return of 3 txns (>10% → flagged); S2 none.
    rates = {r["store_id"]: r for r in results["return_rate_by_store"]}
    assert rates["S1"]["return_transactions"] == 1
    assert rates["S1"]["total_transactions"] == 3
    assert rates["S1"]["return_rate"] == pytest.approx(1 / 3, abs=1e-4)
    assert rates["S1"]["high_return_rate"] is True
    assert rates["S2"]["high_return_rate"] is False

    # Avg transaction value by region excludes the return: East = (20+10)/2 = 15.
    region = {r["region"]: r["avg_transaction_value"] for r in
              results["avg_transaction_value_by_region"]}
    assert region["East"] == 15.0
    assert region["West"] == 50.0

    # Top customers excludes the guest; C1 net spend = 20 + 10 - 10 = 20.
    customers = results["top_10_customers_by_lifetime_spend"]
    assert len(customers) == 1
    assert customers[0]["customer_id"] == "C1"
    assert customers[0]["lifetime_spend"] == 20.0
    assert customers[0]["transaction_count"] == 3
    assert customers[0]["avg_order_value"] == pytest.approx(6.67, abs=1e-2)

    # Net-revenue ranking: S2 ($50) ahead of S1 ($20) in the 30-day window.
    top_stores = results["top_5_stores_by_net_revenue_30d"]["stores"]
    assert [s["store_id"] for s in top_stores] == ["S2", "S1"]
    assert dict((s["store_id"], s["net_revenue"]) for s in top_stores) == {"S2": 50.0, "S1": 20.0}
