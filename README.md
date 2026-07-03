# Mindex Data Engineer / Data Architect Code Challenge

## Overview

Mindex builds and operates data platforms for clients across industries. In this challenge, you'll take raw exports from three legacy systems, build a pipeline that cleans and models the data, and use it to answer real analytical questions.

**Estimated time:** 2–3 hours  
**Required language:** Python 3.10+  
**Database:** SQLite (standard library — no server setup needed)

> **On AI use:** You're welcome to use AI tools (Copilot, ChatGPT, etc.). We're evaluating your judgment, your ability to reason about data problems, and the quality of your decisions — not just whether the code runs. AI can write boilerplate; it's up to you to think critically about the data.

---

## The Scenario

A client has given you three raw CSV exports from their legacy retail systems.  Your job is to build a small but production-minded pipeline that ingests, cleans, and models this data — then answer several business questions from the resulting warehouse.

The source data was exported from systems that have been running for years with minimal governance. Treat it accordingly.

---

## Source Data

Three files live in `data/raw/`:

| File | Description |
|---|---|
| `transactions.csv` | Point-of-sale transactions from the last ~90 days |
| `stores.csv` | Store reference/dimension data |
| `products.csv` | Product catalog |

You can regenerate these files at any time by running:

```bash
python scripts/seed_data.py
```

---

## Your Tasks

### Part 1 — Data Profiling

Write a reusable `profile(df: pd.DataFrame, name: str) -> dict` function that returns a quality summary for any DataFrame, including (at minimum):

- Row count and column count
- Per-column null counts and null percentages
- Duplicate row count
- For numeric columns: min, max, mean, count of zeros, count of negatives
- For columns that appear to contain dates: min date, max date, count of future dates (relative to today)

Run your profiler against all three source files and save the combined output to `output/profiling_report.json`.

---

### Part 2 — Data Cleaning

Build a cleaning pipeline that produces clean, validated DataFrames ready for loading into the warehouse.

For **every** issue you find and address, document it in your README using this table format:

| Issue | File | Count | Decision | Rationale |
|---|---|---|---|---|
| ... | ... | ... | ... | ... |

Your handling of each issue should be deliberate — "I dropped it" and "I kept it with a flag" are both valid answers, but they need to be justified.

---

### Part 3 — Data Modeling

Design and populate a SQLite database at `output/warehouse.db` with a star schema containing at least:

- **`dim_date`** — calendar attributes for every date in the transaction window
- **`dim_store`** — one row per store location
- **`dim_product`** — one row per product
- **`fact_sales`** — one row per transaction, with foreign keys to the dimensions above

You choose the columns. Document your schema in the README, including how you handled:

- Products with more than one price on record
- Returns (negative transactions)
- Any records excluded from the warehouse and why

---

### Part 4 — Analytics

Using SQL (via `sqlite3`) or pandas — your choice, but justify it in your README — answer the following questions. Save all results to `output/analytics.json`.

1. **Top 5 stores by net revenue** in the most recent 30-day window of data (returns should reduce revenue, not be excluded)
2. **Month-over-month revenue change (%)** by product category
3. **Return rate by store** (return transactions ÷ total transactions). Flag any store where the return rate exceeds 10%.
4. **Average transaction value by region** (exclude return transactions)
5. **Top 10 customers by lifetime spend** (exclude guest/anonymous transactions). Include transaction count and average order value per customer.

---

### Part 5 — Tests

Write `pytest` tests in a `tests/` directory covering:

- **Profiling function:** at least 2 tests, including at least one edge case (e.g., empty DataFrame, all-null column)
- **Cleaning transformations:** at least 2 tests that verify specific transformations against known inputs
- **Analytics:** at least 1 test that loads a small controlled fixture into SQLite and validates a known query result

Tests should make meaningful assertions — not just "the function runs without error."

---

### Part 6 — Documentation

Replace or extend this README with your own documentation covering:

- A brief architecture overview (ASCII diagram is fine)
- Your data quality findings table (from Part 2)
- Your schema design and key modeling decisions
- How you would productionize this pipeline (orchestration, incremental loads, observability)
- What you'd do differently with more time

---

## Deliverables

Submit a link to a **public GitHub repository**. Your repo should contain working code that we can clone and run.

Suggested layout (you may restructure as you see fit):

```
├── README.md                  ← your documentation
├── requirements.txt
├── data/
│   └── raw/                   ← original source files (do not modify)
├── output/                    ← generated artifacts (warehouse.db, JSON reports)
├── src/
│   ├── profiler.py
│   ├── cleaner.py
│   ├── loader.py
│   └── analytics.py
└── tests/
    └── test_pipeline.py
```

Include a **`requirements.txt`** and brief setup/run instructions so we can execute your pipeline end-to-end with:

```bash
pip install -r requirements.txt
python src/pipeline.py        # or however you've structured it
pytest tests/
```

---

## Evaluation Criteria

| Area | What we look for |
|---|---|
| **Code quality** | Readable, modular, appropriately abstracted |
| **Data quality handling** | Thoroughness of discovery; defensibility of decisions |
| **Schema design** | Are modeling choices sound and explained? |
| **Analytics accuracy** | Do the queries answer the right question correctly? |
| **Test quality** | Meaningful assertions, edge cases, not just smoke tests |
| **Communication** | Is the README clear, honest, and professional? |

We are **not** looking for a perfect, production-hardened system. We are looking for evidence of how you think, how you communicate tradeoffs, and how you write code that a teammate could pick up and understand.

---

# Implementation Notes

## Part 2 — Data Quality Findings

The cleaning pipeline (`src/cleaner.py`) reads the raw CSVs as strings (so no
value is silently mangled by pandas' type inference — e.g. leading-zero zips),
handles every issue below **deliberately**, and writes a machine-readable log of
what it did to `output/cleaning_report.json`. The counts in that log are
generated by the same code that performs the cleaning, so the table here always
matches what actually ran (regenerate with `python src/cleaner.py`).

**Row counts:** stores 16 → 15 · products 32 → 30 · transactions 505 → 474.

### Reference ("as-of") date

Transactions are a **static historical snapshot** exported on **2026-06-02**.
Future-dated detection is anchored to that extract date, *not* the wall-clock
date the pipeline happens to run. Legitimate transactions cluster on/before
2026-06-01; the three anomalous rows (2026-06-10/18/27) fall after the snapshot
boundary. Anchoring here keeps the pipeline **reproducible** (the same CSVs
always yield the same clean output) and avoids bad future-dated rows silently
"becoming valid" as the real clock advances. In production this date would come
from extract metadata or a run parameter (`clean_all(as_of_date=...)`).

### Findings

| Issue | File | Count | Decision | Rationale |
|---|---|---|---|---|
| Malformed zip code (< 5 digits) | stores | 1 | Zero-pad to 5 chars (`0938` → `00938`), keep as string | Leading-zero zips are valid; preserving them as text avoids data loss. |
| Duplicate `store_id` (near-duplicate row) | stores | 1 | Drop duplicate, keep first by `store_id` | `store_id` is the dimension key and must be unique; the two rows differ only in a reformatted name. |
| Null `region` | stores | 2 | Impute `"Unknown"` | Stores have real transactions; keeping them lets region analytics bucket the unknowns rather than dropping revenue. |
| Exact duplicate product row | products | 1 | Drop exact duplicates | Byte-identical row from a bad extract. |
| Product with more than one price | products | 1 | Keep the highest price as the current catalog price | No effective-date to order the prices; `fact_sales` uses the per-transaction price, so this reference price never affects revenue. |
| Null `category` | products | 5 | Impute `"Unknown"` | Keep the products; category analytics bucket the unknowns. |
| Zero `unit_price` | products | 1 | Keep row, flag `price_valid=False` | Likely a data error, but transactions carry the real price — flag for review rather than silently drop. |
| Mixed date formats (US `MM/DD/YYYY` + EU `DD-MM-YYYY`) | transactions | 20 | Parse all formats to a single ISO datetime | Downstream date logic needs one canonical format. |
| Currency-formatted amount strings (`$X.XX`) | transactions | 25 | Strip `$`/`,` and cast to float | `total_amount` must be numeric for aggregation. |
| Exact duplicate transaction row | transactions | 15 | Drop exact duplicates | Identical rows would double-count revenue. |
| Return transaction (negative qty/amount) | transactions | 30 | Keep, flag `is_return=True` | Returns are real events; analytics require them to reduce net revenue, not be dropped. |
| Null `customer_id` (guest transaction) | transactions | 40 | Keep, flag `is_guest=True` | Valid sales; only excluded from lifetime-spend analytics. |
| Silent discount (`total_amount` ≠ qty × unit_price) | transactions | 20 | Keep recorded `total_amount`, flag `price_mismatch=True` | The recorded total is what the customer actually paid; don't recompute it away. |
| Orphaned `store_id` (not in stores) | transactions | 5 | **Exclude** from warehouse (logged) | No valid store dimension; revenue can't be attributed to a location. |
| Orphaned `product_id` (not in products) | transactions | 3 | **Exclude** from warehouse (logged) | No valid product dimension entry. |
| Zero-quantity transaction | transactions | 5 | **Exclude** from warehouse | Quantity and total are both 0 — no economic event. |
| Future-dated transaction (> 2026-06-02) | transactions | 3 | **Exclude** from warehouse | A sale cannot post after the data was extracted. |

### Cleaning order (transactions)

Type standardization → drop exact duplicates → add analytic flags → exclude
unusable rows. Flags (`is_return`, `is_guest`, `price_mismatch`) are computed
over the **deduplicated** set and *before* exclusions, so their counts describe
the real transactions that survive into the warehouse.
