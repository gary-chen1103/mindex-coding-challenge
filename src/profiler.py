"""
profiler.py  —  Mindex Data Engineer / Data Architect Code Challenge (Part 1)

A reusable data-profiling function that produces a quality summary for any
DataFrame, plus a CLI that profiles the three raw source files and writes a
combined report to ``output/profiling_report.json``.

Design note — why we read every column as a string:
    pandas' default CSV type inference silently *hides* the data problems a
    profiler is supposed to surface. For example ``stores.zip_code`` would load
    as ``int64``, turning ``0938`` into ``938`` (leading-zero data loss), and
    ``transactions.total_amount`` loads as ``object`` because ``$X.XX`` strings
    poison it, so no numeric stats appear at all. We therefore read raw
    (``dtype=str``) and infer each column's type ourselves by attempted
    coercion. This reports the *actual* state of the data — the evidence base
    for the Part 2 cleaning decisions.

Usage:
    python src/profiler.py          # or: python -m src.profiler
"""

from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path
from typing import Optional

import pandas as pd

# A column is classified numeric/date only if a strong majority of its
# non-null values coerce successfully. This tolerates a handful of dirty
# values (e.g. "$" amounts) without misclassifying a genuinely mixed column.
MAJORITY_THRESHOLD = 0.9

# Date formats present in the raw data (ISO plus the injected US / EU variants).
DATE_FORMATS = ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y")

REPO_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = REPO_ROOT / "data" / "raw"
OUTPUT_DIR = REPO_ROOT / "output"
SOURCES = ("stores", "products", "transactions")


# ── Coercion helpers ───────────────────────────────────────────────────────────

def _coerce_numeric(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Attempt to parse a string series as numbers.

    Strips currency symbols, thousands separators and whitespace before
    coercing. Returns ``(parsed, success_mask, anomaly_mask)`` where
    ``success_mask`` is True for non-null values that parsed to a number, and
    ``anomaly_mask`` is True for values that only parsed *after* cleaning (e.g.
    ``"$392.40"``) — i.e. numbers stored in a non-canonical format.
    """
    cleaned = (
        series.astype("string")
        .str.replace(r"[$,]", "", regex=True)
        .str.strip()
    )
    parsed = pd.to_numeric(cleaned, errors="coerce")
    success_mask = parsed.notna() & series.notna()
    raw_parsed = pd.to_numeric(series, errors="coerce")
    anomaly_mask = success_mask & raw_parsed.isna()
    return parsed, success_mask, anomaly_mask


def _coerce_dates(series: pd.Series) -> tuple[pd.Series, pd.Series, pd.Series]:
    """Attempt to parse a string series as dates across all known formats.

    Values are tried against each format in turn and the results combined, so a
    column mixing ``MM/DD/YYYY`` and ``DD-MM-YYYY`` parses fully. Returns
    ``(parsed, success_mask, anomaly_mask)`` where ``anomaly_mask`` is True for
    dates that parsed but are not in canonical ISO ``YYYY-MM-DD`` form.
    """
    parsed = pd.Series(pd.NaT, index=series.index, dtype="datetime64[ns]")
    for fmt in DATE_FORMATS:
        remaining = parsed.isna()
        if not remaining.any():
            break
        attempt = pd.to_datetime(series[remaining], format=fmt, errors="coerce")
        parsed.loc[remaining] = attempt
    success_mask = parsed.notna() & series.notna()
    iso_parsed = pd.to_datetime(series, format="%Y-%m-%d", errors="coerce")
    anomaly_mask = success_mask & iso_parsed.isna()
    return parsed, success_mask, anomaly_mask


def _majority_ok(success_mask: pd.Series, non_null_count: int) -> bool:
    """True if at least MAJORITY_THRESHOLD of non-null values coerced."""
    if non_null_count == 0:
        return False
    return success_mask.sum() / non_null_count >= MAJORITY_THRESHOLD


def _infer_type(
    column_name: str,
    non_null: pd.Series,
    date_mask: pd.Series,
    numeric_mask: pd.Series,
) -> str:
    """Classify a column as 'date', 'numeric' or 'string'.

    Dates are checked first so that date-like strings are never mistaken for
    numbers. A column whose name contains 'date' is treated as a date whenever
    *any* value parses, which keeps an all-null or sparsely-populated date
    column correctly typed.
    """
    non_null_count = len(non_null)
    name_is_date = "date" in column_name.lower()

    if name_is_date and date_mask.any():
        return "date"
    if _majority_ok(date_mask, non_null_count):
        return "date"
    if _majority_ok(numeric_mask, non_null_count):
        return "numeric"
    return "string"


# ── Profiling ──────────────────────────────────────────────────────────────────

def profile(df: pd.DataFrame, name: str, today: Optional[date] = None) -> dict:
    """Return a data-quality summary for ``df``.

    Assumes ``df`` was read with all columns as strings (see ``read_raw``);
    empty strings are treated as nulls. ``today`` defaults to the real current
    date and controls the "future date" comparison; it is a parameter so tests
    can pin it deterministically.
    """
    if today is None:
        today = date.today()
    today_ts = pd.Timestamp(today)

    row_count = int(len(df))

    # Normalize empty / whitespace-only strings to NA so they count as nulls.
    normalized = df.replace(r"^\s*$", pd.NA, regex=True)

    report: dict = {
        "name": name,
        "row_count": row_count,
        "column_count": int(df.shape[1]),
        "duplicate_row_count": int(normalized.duplicated().sum()),
        "columns": {},
    }

    for col in normalized.columns:
        series = normalized[col]
        null_count = int(series.isna().sum())
        col_report: dict = {
            "dtype": str(df[col].dtype),
            "null_count": null_count,
            "null_pct": round(100.0 * null_count / row_count, 2) if row_count else 0.0,
        }

        non_null = series.dropna()
        date_parsed, date_mask, date_anomaly = _coerce_dates(series)
        numeric_parsed, numeric_mask, numeric_anomaly = _coerce_numeric(series)
        inferred = _infer_type(col, non_null, date_mask, numeric_mask)
        col_report["inferred_type"] = inferred

        if inferred == "numeric":
            values = numeric_parsed[numeric_mask]
            col_report.update(
                {
                    "min": round(float(values.min()), 2) if not values.empty else None,
                    "max": round(float(values.max()), 2) if not values.empty else None,
                    "mean": round(float(values.mean()), 2) if not values.empty else None,
                    "zero_count": int((values == 0).sum()),
                    "negative_count": int((values < 0).sum()),
                    # Non-null values that could not be parsed as a number at all.
                    "coercion_failures": int(len(non_null) - numeric_mask.sum()),
                    # Values that parsed only after cleaning, e.g. "$12.00" — a
                    # cleaning task, not a broken value.
                    "format_anomaly_count": int(numeric_anomaly.sum()),
                }
            )
        elif inferred == "date":
            values = date_parsed[date_mask]
            col_report.update(
                {
                    "min_date": values.min().date().isoformat() if not values.empty else None,
                    "max_date": values.max().date().isoformat() if not values.empty else None,
                    "future_date_count": int((values > today_ts).sum()),
                    # Non-null values matching no known date format.
                    "coercion_failures": int(len(non_null) - date_mask.sum()),
                    # Dates parsed from a non-ISO format (e.g. MM/DD/YYYY).
                    "format_anomaly_count": int(date_anomaly.sum()),
                }
            )

        report["columns"][col] = col_report

    return report


# ── I/O ──────────────────────────────────────────────────────────────────────

def read_raw(path: Path) -> pd.DataFrame:
    """Read a CSV with every column as a string so raw values survive intact."""
    return pd.read_csv(path, dtype=str, keep_default_na=True)


def main() -> None:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    today = date.today()

    datasets: dict = {}
    for name in SOURCES:
        df = read_raw(DATA_DIR / f"{name}.csv")
        result = profile(df, name, today=today)
        datasets[name] = result
        dupes = result["duplicate_row_count"]
        print(
            f"  {name}: {result['row_count']} rows, "
            f"{result['column_count']} cols, {dupes} duplicate rows"
        )

    report = {
        "generated_at": datetime.now().isoformat(timespec="seconds"),
        "today": today.isoformat(),
        "datasets": datasets,
    }
    out_path = OUTPUT_DIR / "profiling_report.json"
    with out_path.open("w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nProfiling report written to: {out_path}")


if __name__ == "__main__":
    main()
