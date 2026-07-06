"""
cleaner.py  —  Mindex Data Engineer / Data Architect Code Challenge (Part 2)

Turns the three raw CSVs into clean, validated DataFrames ready to load into the
warehouse (Part 3). Every issue discovered during profiling is handled
*deliberately* — some values are transformed or imputed, some rows are dropped,
some are kept with a flag — and each decision is recorded in a structured issue
log written to ``output/cleaning_report.json``. That log is the source of truth
for the README's data-quality table, so the documented counts always match what
the code actually did.

Cleaning order for transactions is deliberate: transform types → drop exact
duplicates → add flags → exclude unusable rows. Flags are added before the
exclusions so counts (e.g. returns, guests) are taken over the deduplicated set.

Usage:
    python -m src.cleaner
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

from src.profiler import DATE_FORMATS, read_raw

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "raw"
OUTPUT_DIR = REPO_ROOT / "output"

UNKNOWN = "Unknown"

# The data extract date — the day the source systems were exported. A sale
# cannot post *after* the data was pulled, so any later transaction_date is a
# data error, not a real future sale. We anchor "future-dated" detection to
# this snapshot boundary rather than the wall-clock date for two reasons:
#   1. Reproducibility — the same static CSVs must yield the same clean output
#      no matter what day the pipeline is run. Using date.today() would let the
#      3 injected future-dated rows silently "become valid" once the real clock
#      passes them, which is exactly the kind of drift a pipeline must not have.
#   2. Correctness — legitimate transactions cluster on/before 2026-06-01, with
#      a clear gap before the anomalous rows dated 2026-06-10/18/27; 2026-06-02
#      is the snapshot boundary that separates the two.
# In a live system this would come from extract metadata / a run parameter.
EXTRACT_DATE = date(2026, 6, 2)


# ── Shared parsing helpers ─────────────────────────────────────────────────────

def _to_numeric(series: pd.Series) -> pd.Series:
    """Parse a string series to numbers, stripping currency symbols/commas.

    Mirrors the coercion used by the profiler so cleaning and profiling agree on
    what counts as numeric.
    """
    cleaned = series.astype("string").str.replace(r"[$,]", "", regex=True).str.strip()
    return pd.to_numeric(cleaned, errors="coerce")


def _to_datetime(series: pd.Series) -> pd.Series:
    """Parse a string series to datetimes across all known formats."""
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        remaining = parsed.isna()
        if not remaining.any():
            break
        parsed.loc[remaining] = pd.to_datetime(
            series[remaining], format=fmt, errors="coerce"
        )
    return parsed


def _blank_to_na(df: pd.DataFrame) -> pd.DataFrame:
    """Normalize empty / whitespace-only strings to NA (raw load gives strings)."""
    return df.replace(r"^\s*$", pd.NA, regex=True)


def _issue(issues: list, name: str, file: str, count: int, decision: str, rationale: str) -> None:
    """Append an issue record only when it actually occurred (count > 0)."""
    if count > 0:
        issues.append(
            {
                "issue": name,
                "file": file,
                "count": int(count),
                "decision": decision,
                "rationale": rationale,
            }
        )


# ── Stores ──────────────────────────────────────────────────────────────────

def clean_stores(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    df = _blank_to_na(df.copy())
    issues: list = []

    # 1. Malformed zip codes (fewer than 5 digits) → zero-pad, keep as string.
    malformed_zip = df["zip_code"].str.len().lt(5).fillna(False)
    _issue(
        issues, "Malformed zip code (< 5 digits)", "stores", int(malformed_zip.sum()),
        "Zero-pad to 5 characters (e.g. 0938 → 00938)",
        "Leading-zero zip codes are valid; preserve as a 5-char string.",
    )
    df["zip_code"] = df["zip_code"].str.zfill(5)

    # 2. Near-duplicate store_id (same id, differing attributes) → keep first.
    dupe_ids = int(df["store_id"].duplicated().sum())
    _issue(
        issues, "Duplicate store_id (near-duplicate row)", "stores", dupe_ids,
        "Drop duplicate, keep first occurrence by store_id",
        "store_id is the dimension key and must be unique.",
    )
    df = df.drop_duplicates(subset="store_id", keep="first")

    # 3. Null region → impute "Unknown".
    null_region = int(df["region"].isna().sum())
    _issue(
        issues, "Null region", "stores", null_region,
        'Impute "Unknown"',
        "Stores have real transactions; keep them and let region analytics bucket them.",
    )
    df["region"] = df["region"].fillna(UNKNOWN)

    # Standardize opened_date to ISO date strings.
    df["opened_date"] = _to_datetime(df["opened_date"]).dt.date.astype("string")

    return df.reset_index(drop=True), issues


# ── Products ──────────────────────────────────────────────────────────────────

def clean_products(df: pd.DataFrame) -> tuple[pd.DataFrame, list]:
    df = _blank_to_na(df.copy())
    issues: list = []

    df["unit_price"] = _to_numeric(df["unit_price"])

    # 4. Exact duplicate rows → drop.
    exact_dupes = int(df.duplicated().sum())
    _issue(
        issues, "Exact duplicate product row", "products", exact_dupes,
        "Drop exact duplicates",
        "Identical rows are a bad data extract.",
    )
    df = df.drop_duplicates()

    # 5. Multiple prices per product_id → keep the highest as current catalog price.
    multi_price = int((df.groupby("product_id")["unit_price"].nunique() > 1).sum())
    _issue(
        issues, "Product with more than one price on record", "products", multi_price,
        "Keep the highest price as the current catalog price",
        "No effective-date to order the prices; fact_sales uses the per-transaction "
        "price, so this reference price does not affect revenue.",
    )
    df = (
        df.sort_values("unit_price", ascending=False)
        .drop_duplicates(subset="product_id", keep="first")
        .sort_index()
    )

    # 6. Null category → impute "Unknown".
    null_cat = int(df["category"].isna().sum())
    _issue(
        issues, "Null category", "products", null_cat,
        'Impute "Unknown"',
        "Keep products; category analytics bucket the unknowns.",
    )
    df["category"] = df["category"].fillna(UNKNOWN)

    # 7. Zero unit_price → keep but flag as invalid for review.
    zero_price = int((df["unit_price"] == 0).sum())
    _issue(
        issues, "Zero unit_price", "products", zero_price,
        "Keep row, flag price_valid=False",
        "Likely a data error, but transactions carry the real price; flag rather "
        "than silently drop.",
    )
    df["price_valid"] = df["unit_price"] > 0

    return df.reset_index(drop=True), issues


# ── Transactions ──────────────────────────────────────────────────────────────

def clean_transactions(
    df: pd.DataFrame,
    valid_store_ids: set,
    valid_product_ids: set,
    as_of_date: date,
) -> tuple[pd.DataFrame, list]:
    df = _blank_to_na(df.copy())
    issues: list = []
    as_of_ts = pd.Timestamp(as_of_date)

    # 8/9. Standardize types: dates → datetime, amounts/qty/price → numeric.
    non_iso = int((df["transaction_date"].notna() & df["transaction_date"]
                   .str.match(r"^\d{4}-\d{2}-\d{2}$").eq(False)).sum())
    currency = int(df["total_amount"].str.contains(r"[$,]", na=False).sum())
    df["transaction_date"] = _to_datetime(df["transaction_date"])
    for col in ("quantity", "unit_price", "total_amount"):
        df[col] = _to_numeric(df[col])
    df["quantity"] = df["quantity"].astype("Int64")
    _issue(
        issues, "Mixed date formats (US/EU)", "transactions", non_iso,
        "Parse to ISO datetime",
        "Downstream date logic needs a single canonical format.",
    )
    _issue(
        issues, "Currency-formatted amount strings ($X.XX)", "transactions", currency,
        "Strip $/, and cast to float",
        "total_amount must be numeric for aggregation.",
    )

    # 16. Exact duplicate rows (same transaction_id, all columns equal) → drop.
    exact_dupes = int(df.duplicated().sum())
    _issue(
        issues, "Exact duplicate transaction row", "transactions", exact_dupes,
        "Drop exact duplicates",
        "Identical rows would double-count revenue.",
    )
    df = df.drop_duplicates()

    # Flags (computed over the deduplicated set, before exclusions).
    df["is_return"] = df["quantity"] < 0
    df["is_guest"] = df["customer_id"].isna()
    expected = (df["quantity"] * df["unit_price"]).round(2)
    df["price_mismatch"] = df["total_amount"].round(2).ne(expected) & df["total_amount"].notna()

    # 17/13/10. Kept-with-flag issues (recorded, not removed).
    _issue(
        issues, "Return transaction (negative qty/amount)", "transactions",
        int(df["is_return"].sum()),
        "Keep, flag is_return=True",
        "Returns are real events; Part 4 requires them to reduce net revenue.",
    )
    _issue(
        issues, "Null customer_id (guest transaction)", "transactions",
        int(df["is_guest"].sum()),
        "Keep, flag is_guest=True",
        "Valid sales; only excluded from lifetime-spend analytics.",
    )
    _issue(
        issues, "Silent discount (total ≠ qty × unit_price)", "transactions",
        int(df["price_mismatch"].sum()),
        "Keep recorded total_amount, flag price_mismatch=True",
        "The recorded total is what the customer actually paid; do not recompute.",
    )

    # 11/12/14/15. Exclusions — record counts, then drop.
    orphan_store = ~df["store_id"].isin(valid_store_ids)
    orphan_product = ~df["product_id"].isin(valid_product_ids)
    zero_qty = df["quantity"] == 0
    future = df["transaction_date"] > as_of_ts

    _issue(
        issues, "Orphaned store_id (not in stores)", "transactions", int(orphan_store.sum()),
        "Exclude from warehouse (logged)",
        "No valid store dimension; revenue cannot be attributed to a location.",
    )
    _issue(
        issues, "Orphaned product_id (not in products)", "transactions", int(orphan_product.sum()),
        "Exclude from warehouse (logged)",
        "No valid product dimension entry.",
    )
    _issue(
        issues, "Zero-quantity transaction", "transactions", int(zero_qty.sum()),
        "Exclude from warehouse",
        "Quantity and total are both 0 — no economic event.",
    )
    _issue(
        issues, f"Future-dated transaction (> {as_of_date.isoformat()})", "transactions",
        int(future.sum()),
        "Exclude from warehouse",
        "A sale cannot occur after the extract date.",
    )

    df = df[~(orphan_store | orphan_product | zero_qty | future)]
    return df.reset_index(drop=True), issues


# ── Orchestration ─────────────────────────────────────────────────────────────

@dataclass
class CleanResult:
    stores: pd.DataFrame
    products: pd.DataFrame
    transactions: pd.DataFrame
    issues: list = field(default_factory=list)
    row_counts: dict = field(default_factory=dict)


def clean_all(data_dir: Path = DATA_DIR, as_of_date: Optional[date] = None) -> CleanResult:
    """Read raw CSVs and return cleaned DataFrames plus the combined issue log.

    Stores and products are cleaned first so their (deduplicated) id sets can be
    used to detect orphaned foreign keys in the transactions.

    ``as_of_date`` defaults to the data extract date (see ``EXTRACT_DATE``) so
    downstream consumers get reproducible, correctly-filtered output; tests pass
    their own value.
    """
    if as_of_date is None:
        as_of_date = EXTRACT_DATE

    raw_stores = read_raw(data_dir / "stores.csv")
    raw_products = read_raw(data_dir / "products.csv")
    raw_transactions = read_raw(data_dir / "transactions.csv")

    stores, store_issues = clean_stores(raw_stores)
    products, product_issues = clean_products(raw_products)
    transactions, tx_issues = clean_transactions(
        raw_transactions, set(stores["store_id"]), set(products["product_id"]), as_of_date
    )

    row_counts = {
        "stores": {"raw": len(raw_stores), "clean": len(stores)},
        "products": {"raw": len(raw_products), "clean": len(products)},
        "transactions": {"raw": len(raw_transactions), "clean": len(transactions)},
    }
    return CleanResult(
        stores=stores,
        products=products,
        transactions=transactions,
        issues=store_issues + product_issues + tx_issues,
        row_counts=row_counts,
    )


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    as_of_date = EXTRACT_DATE
    result = clean_all(as_of_date=as_of_date)

    files: dict = {}
    for name in ("stores", "products", "transactions"):
        counts = result.row_counts[name]
        files[name] = {
            "raw_rows": counts["raw"],
            "clean_rows": counts["clean"],
            "issues": [i for i in result.issues if i["file"] == name],
        }
        print(f"  {name}: {counts['raw']} → {counts['clean']} rows "
              f"({len(files[name]['issues'])} issue types handled)")

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "as_of_date": as_of_date.isoformat(),
        "files": files,
    }
    out_path = OUTPUT_DIR / "cleaning_report.json"
    with out_path.open("w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nCleaning report written to: {out_path}")


if __name__ == "__main__":
    main()
