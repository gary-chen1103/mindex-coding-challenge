"""
loader.py  —  Mindex Data Engineer / Data Architect Code Challenge (Part 3)

Builds a SQLite **star schema** at ``output/warehouse.db`` from the cleaned,
validated DataFrames produced by ``cleaner.clean_all()`` (Part 2).

Schema
------
Three dimensions and one fact, each dimension keyed by an integer **surrogate**
key (stable, join-friendly, independent of the source natural keys) while
retaining the natural business key for traceability:

    dim_date     (date_key PK)      one row per calendar day in the tx window
    dim_store    (store_key PK)     one row per store location
    dim_product  (product_key PK)   one row per product
    fact_sales   (sale_key PK)      one row per surviving transaction,
                                     FK → each dimension

Key modeling decisions (see README for the full write-up)
---------------------------------------------------------
* Products with more than one price   — resolved upstream in cleaning: the
  highest price is stored as the catalog reference in ``dim_product.unit_price``.
  Revenue is never computed from it — ``fact_sales`` carries the *per-transaction*
  ``unit_price``/``total_amount`` — so the reference price is informational only.
* Returns (negative transactions)     — kept as ordinary fact rows with negative
  ``quantity``/``total_amount`` and ``is_return = 1``, so they net down revenue
  in aggregate rather than being dropped.
* Excluded records                    — orphaned FKs, zero-quantity and
  future-dated rows are removed during cleaning (Part 2) and logged in
  ``output/cleaning_report.json``; they never reach the warehouse.
* Guest transactions                  — kept, ``customer_id`` is NULL and
  ``is_guest = 1``; excluded only from customer-level analytics (Part 4).

Usage:
    python src/loader.py            # or: python -m src.loader
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Optional

import pandas as pd

from src.cleaner import OUTPUT_DIR, CleanResult, clean_all

DB_PATH = OUTPUT_DIR / "warehouse.db"

# Declared constraints (PK/FK/UNIQUE/NOT NULL) make the star schema explicit and
# let SQLite enforce referential integrity — better for a modeling deliverable
# than letting pandas.to_sql infer loose, key-less tables.
SCHEMA_SQL = """
DROP TABLE IF EXISTS fact_sales;
DROP TABLE IF EXISTS dim_date;
DROP TABLE IF EXISTS dim_store;
DROP TABLE IF EXISTS dim_product;

CREATE TABLE dim_date (
    date_key     INTEGER PRIMARY KEY,   -- YYYYMMDD surrogate
    date         TEXT    NOT NULL,      -- ISO YYYY-MM-DD
    year         INTEGER NOT NULL,
    quarter      INTEGER NOT NULL,
    month        INTEGER NOT NULL,
    month_name   TEXT    NOT NULL,
    day          INTEGER NOT NULL,
    day_of_week  INTEGER NOT NULL,      -- 0 = Monday
    day_name     TEXT    NOT NULL,
    week_of_year INTEGER NOT NULL,
    is_weekend   INTEGER NOT NULL       -- 0 / 1
);

CREATE TABLE dim_store (
    store_key    INTEGER PRIMARY KEY,
    store_id     TEXT    NOT NULL UNIQUE,
    store_name   TEXT,
    city         TEXT,
    state        TEXT,
    zip_code     TEXT,
    region       TEXT,
    opened_date  TEXT
);

CREATE TABLE dim_product (
    product_key  INTEGER PRIMARY KEY,
    product_id   TEXT    NOT NULL UNIQUE,
    product_name TEXT,
    category     TEXT,
    unit_price   REAL,                  -- catalog reference price (see module docstring)
    supplier_id  TEXT,
    price_valid  INTEGER NOT NULL       -- 0 / 1
);

CREATE TABLE fact_sales (
    sale_key       INTEGER PRIMARY KEY AUTOINCREMENT,
    transaction_id TEXT    NOT NULL,    -- degenerate dimension (business tx id)
    date_key       INTEGER NOT NULL REFERENCES dim_date(date_key),
    store_key      INTEGER NOT NULL REFERENCES dim_store(store_key),
    product_key    INTEGER NOT NULL REFERENCES dim_product(product_key),
    customer_id    TEXT,                -- degenerate dimension; NULL for guest
    quantity       INTEGER NOT NULL,
    unit_price     REAL,                -- price as recorded on the transaction
    total_amount   REAL    NOT NULL,    -- amount as recorded (what was paid)
    is_return      INTEGER NOT NULL,    -- 0 / 1
    is_guest       INTEGER NOT NULL,    -- 0 / 1
    price_mismatch INTEGER NOT NULL     -- 0 / 1  (total_amount != qty * unit_price)
);

CREATE INDEX idx_fact_date    ON fact_sales(date_key);
CREATE INDEX idx_fact_store   ON fact_sales(store_key);
CREATE INDEX idx_fact_product ON fact_sales(product_key);
"""


# ── Dimension / fact construction ───────────────────────────────────────────────

def build_dim_date(transactions: pd.DataFrame) -> pd.DataFrame:
    """One row per calendar day spanning the transaction window (inclusive).

    Every date between the min and max transaction date is present — including
    days with no sales — so time-series joins never drop a period.
    """
    dmin = transactions["transaction_date"].min().normalize()
    dmax = transactions["transaction_date"].max().normalize()
    days = pd.date_range(dmin, dmax, freq="D")

    dim = pd.DataFrame({"date": days})
    dim["date_key"] = dim["date"].dt.strftime("%Y%m%d").astype(int)
    dim["date"] = dim["date"].dt.strftime("%Y-%m-%d")
    dim["year"] = days.year
    dim["quarter"] = days.quarter
    dim["month"] = days.month
    dim["month_name"] = days.strftime("%B")
    dim["day"] = days.day
    dim["day_of_week"] = days.dayofweek           # 0 = Monday
    dim["day_name"] = days.strftime("%A")
    dim["week_of_year"] = days.isocalendar().week.astype(int).to_numpy()
    dim["is_weekend"] = (days.dayofweek >= 5).astype(int)
    return dim


def build_dim_store(stores: pd.DataFrame) -> pd.DataFrame:
    dim = stores.copy().reset_index(drop=True)
    dim.insert(0, "store_key", range(1, len(dim) + 1))
    return dim


def build_dim_product(products: pd.DataFrame) -> pd.DataFrame:
    dim = products.copy().reset_index(drop=True)
    dim.insert(0, "product_key", range(1, len(dim) + 1))
    dim["price_valid"] = dim["price_valid"].astype(int)
    return dim


def build_fact_sales(
    transactions: pd.DataFrame,
    dim_store: pd.DataFrame,
    dim_product: pd.DataFrame,
) -> pd.DataFrame:
    """Resolve each transaction's natural keys to dimension surrogate keys."""
    fact = transactions.copy()
    fact["date_key"] = fact["transaction_date"].dt.strftime("%Y%m%d").astype(int)
    fact = fact.merge(
        dim_store[["store_key", "store_id"]], on="store_id", how="left"
    ).merge(
        dim_product[["product_key", "product_id"]], on="product_id", how="left"
    )

    for flag in ("is_return", "is_guest", "price_mismatch"):
        fact[flag] = fact[flag].astype(int)

    return fact[
        [
            "transaction_id", "date_key", "store_key", "product_key", "customer_id",
            "quantity", "unit_price", "total_amount",
            "is_return", "is_guest", "price_mismatch",
        ]
    ]


# ── Persistence ────────────────────────────────────────────────────────────────

def _rows(df: pd.DataFrame, cols: list[str]) -> list[tuple]:
    """DataFrame → list of tuples with pandas NA/NaN/NaT converted to None."""
    subset = df[cols].astype(object)
    subset = subset.where(pd.notna(subset), None)
    return list(subset.itertuples(index=False, name=None))


def write_warehouse(
    db_path: Path,
    dim_date: pd.DataFrame,
    dim_store: pd.DataFrame,
    dim_product: pd.DataFrame,
    fact_sales: pd.DataFrame,
) -> None:
    """Create the schema and bulk-load every table inside one transaction."""
    db_path.parent.mkdir(parents=True, exist_ok=True)
    if db_path.exists():
        db_path.unlink()

    conn = sqlite3.connect(db_path)
    try:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.executescript(SCHEMA_SQL)

        date_cols = [
            "date_key", "date", "year", "quarter", "month", "month_name",
            "day", "day_of_week", "day_name", "week_of_year", "is_weekend",
        ]
        store_cols = [
            "store_key", "store_id", "store_name", "city", "state",
            "zip_code", "region", "opened_date",
        ]
        product_cols = [
            "product_key", "product_id", "product_name", "category",
            "unit_price", "supplier_id", "price_valid",
        ]
        fact_cols = [
            "transaction_id", "date_key", "store_key", "product_key", "customer_id",
            "quantity", "unit_price", "total_amount",
            "is_return", "is_guest", "price_mismatch",
        ]

        conn.executemany(
            f"INSERT INTO dim_date ({','.join(date_cols)}) "
            f"VALUES ({','.join('?' * len(date_cols))})",
            _rows(dim_date, date_cols),
        )
        conn.executemany(
            f"INSERT INTO dim_store ({','.join(store_cols)}) "
            f"VALUES ({','.join('?' * len(store_cols))})",
            _rows(dim_store, store_cols),
        )
        conn.executemany(
            f"INSERT INTO dim_product ({','.join(product_cols)}) "
            f"VALUES ({','.join('?' * len(product_cols))})",
            _rows(dim_product, product_cols),
        )
        conn.executemany(
            f"INSERT INTO fact_sales ({','.join(fact_cols)}) "
            f"VALUES ({','.join('?' * len(fact_cols))})",
            _rows(fact_sales, fact_cols),
        )
        conn.commit()
    finally:
        conn.close()


# ── Orchestration ────────────────────────────────────────────────────────────

def build_warehouse(
    db_path: Path = DB_PATH,
    clean: Optional[CleanResult] = None,
) -> dict:
    """Build the full warehouse and return a small summary of what was loaded.

    ``clean`` defaults to a fresh ``clean_all()`` run; tests may pass a
    ``CleanResult`` built from a controlled fixture.
    """
    if clean is None:
        clean = clean_all()

    dim_date = build_dim_date(clean.transactions)
    dim_store = build_dim_store(clean.stores)
    dim_product = build_dim_product(clean.products)
    fact_sales = build_fact_sales(clean.transactions, dim_store, dim_product)

    write_warehouse(db_path, dim_date, dim_store, dim_product, fact_sales)

    return {
        "db_path": str(db_path),
        "dim_date": len(dim_date),
        "dim_store": len(dim_store),
        "dim_product": len(dim_product),
        "fact_sales": len(fact_sales),
        "date_range": [dim_date["date"].min(), dim_date["date"].max()],
    }


def main() -> None:
    summary = build_warehouse()
    print(f"  dim_date:    {summary['dim_date']:>4} rows "
          f"({summary['date_range'][0]} → {summary['date_range'][1]})")
    print(f"  dim_store:   {summary['dim_store']:>4} rows")
    print(f"  dim_product: {summary['dim_product']:>4} rows")
    print(f"  fact_sales:  {summary['fact_sales']:>4} rows")
    print(f"\nWarehouse written to: {summary['db_path']}")


if __name__ == "__main__":
    main()
