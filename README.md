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

## Setup & Run

```bash
pip install -r requirements.txt

# Run the whole pipeline end-to-end (Parts 1–4), regenerating every artifact
# under output/: profiling_report.json, cleaning_report.json, warehouse.db,
# analytics.json.
python -m src.pipeline

pytest                       # Part 5 — 7 tests
```

The modules can also be run individually, in order — each is invoked with
`python -m` (not `python src/<file>.py`) so the `src` package resolves:

```bash
python -m src.profiler       # Part 1 → output/profiling_report.json
python -m src.cleaner        # Part 2 → output/cleaning_report.json
python -m src.loader         # Part 3 → output/warehouse.db (re-cleans upstream)
python -m src.analytics      # Part 4 → output/analytics.json (needs the warehouse)
```

`src/pipeline.py` is a thin orchestrator that calls each stage's `main()` in
order, so a full run produces the same artifacts as running the stages
individually.

## Architecture

Four stages, one direction of flow. Each stage reads the previous stage's output
(or the raw files), does one job, and writes an inspectable artifact — so any
stage can be re-run, tested, or debugged in isolation.

```
        data/raw/*.csv   (stores, products, transactions — never modified)
              │
              ▼
     ┌──────────────────┐
     │  profiler.py      │  read every column as string → infer types →
     │  (Part 1)         │  quality stats            ──▶ output/profiling_report.json
     └────────┬──────────┘
              │  raw CSVs
              ▼
     ┌──────────────────┐
     │  cleaner.py       │  deliberate fixes (impute / dedup / flag /
     │  (Part 2)         │  exclude) + analytic flags
     │                   │                           ──▶ output/cleaning_report.json
     └────────┬──────────┘
              │  CleanResult(stores, products, transactions)
              ▼
     ┌──────────────────┐
     │  loader.py        │  surrogate keys + star schema, FK-enforced
     │  (Part 3)         │                           ──▶ output/warehouse.db
     └────────┬──────────┘
              │  warehouse.db (dim_date · dim_store · dim_product · fact_sales)
              ▼
     ┌──────────────────┐
     │  analytics.py     │  5 business questions in SQL
     │  (Part 4)         │                           ──▶ output/analytics.json
     └──────────────────┘

  pipeline.py  orchestrates all four stages in order (python -m src.pipeline).
  tests/       (Part 5) validate each stage against small, hand-computed fixtures.
```

| Module | Part | Responsibility | Output |
|---|---|---|---|
| `profiler.py` | 1 | Type-inferring data profile of each raw file | `profiling_report.json` |
| `cleaner.py` | 2 | Deliberate cleaning + analytic flags → `CleanResult` | `cleaning_report.json` |
| `loader.py` | 3 | Star-schema warehouse with enforced integrity | `warehouse.db` |
| `analytics.py` | 4 | Business questions over the warehouse | `analytics.json` |
| `pipeline.py` | — | End-to-end orchestration | all of the above |

**Design principles.** (1) *Read raw, decide explicitly* — every column is read as
a string so pandas' type inference can't silently mangle data (e.g. leading-zero
zips); the profiler surfaces problems and the cleaner resolves each one on the
record. (2) *Every decision is logged* — cleaning writes a machine-readable report
whose counts are produced by the same code that cleans, so the docs can't drift
from what ran. (3) *Push correctness into the schema* — PK/FK/UNIQUE/NOT NULL are
declared in DDL so the database itself rejects an invalid load. (4) *Testable
seams* — each stage is a pure-ish function accepting inputs and returning data
(`clean_all()`, `build_warehouse(clean=...)`, `run_analytics(db_path=...)`), so
tests inject controlled fixtures instead of touching the real files.

The **data quality findings table** and **schema design / modeling decisions**
that Part 6 also asks for are documented in the Part 2 and Part 3 sections below.

## Part 2 — Data Quality Findings

The cleaning pipeline (`src/cleaner.py`) reads the raw CSVs as strings (so no
value is silently mangled by pandas' type inference — e.g. leading-zero zips),
handles every issue below **deliberately**, and writes a machine-readable log of
what it did to `output/cleaning_report.json`. The counts in that log are
generated by the same code that performs the cleaning, so the table here always
matches what actually ran (regenerate with `python -m src.cleaner`).

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

## Part 3 — Data Modeling

`src/loader.py` builds a **star schema** at `output/warehouse.db` (SQLite,
stdlib `sqlite3`) from the cleaned DataFrames. Rebuild with
`python -m src.loader`.

```
                 ┌──────────────┐
                 │   dim_date   │
                 │  (date_key)  │
                 └──────┬───────┘
                        │
  ┌────────────┐   ┌────┴─────────┐   ┌──────────────┐
  │ dim_store  │   │  fact_sales  │   │ dim_product  │
  │(store_key) ├───┤  (sale_key)  ├───┤(product_key) │
  └────────────┘   └──────┬───────┘   └──────────────┘
                          │  degenerate dims:
                          │  transaction_id, customer_id
```

Loaded rows: `dim_date` 89 (2026-03-05 → 2026-06-01) · `dim_store` 15 ·
`dim_product` 30 · `fact_sales` 474.

### Tables

| Table | Grain | Key columns | Notable attributes |
|---|---|---|---|
| `dim_date` | one calendar day | `date_key` (PK, `YYYYMMDD`) | `year, quarter, month, month_name, day_of_week, day_name, week_of_year, is_weekend` — spans every day in the tx window, gaps included |
| `dim_store` | one store | `store_key` (PK, surrogate), `store_id` (natural, UNIQUE) | `store_name, city, state, zip_code, region, opened_date` |
| `dim_product` | one product | `product_key` (PK, surrogate), `product_id` (natural, UNIQUE) | `product_name, category, unit_price` (catalog ref), `supplier_id, price_valid` |
| `fact_sales` | one transaction | `sale_key` (PK), FKs → all three dims | `quantity, unit_price, total_amount, is_return, is_guest, price_mismatch`; `transaction_id` + `customer_id` as degenerate dimensions |

**Key choices.** Integer **surrogate keys** on every dimension (stable, compact
joins, decoupled from source keys) with the natural business key retained for
traceability. `date_key` uses the conventional `YYYYMMDD` integer. FK, UNIQUE and
NOT NULL constraints are declared in DDL and `PRAGMA foreign_keys` is enabled, so
SQLite enforces referential integrity at load time (verified: 0 orphan facts).

### Required modeling decisions

- **Products with more than one price** — resolved in cleaning: the higher price
  is stored as the catalog reference in `dim_product.unit_price`. Revenue is
  **never** derived from it — `fact_sales` carries the per-transaction
  `unit_price`/`total_amount` — so the reference price is informational only.
- **Returns (negative transactions)** — kept as ordinary fact rows with negative
  `quantity`/`total_amount` and `is_return = 1`. They net down revenue in
  aggregate (30 rows, −$9,952.03) instead of being excluded.
- **Records excluded from the warehouse** — the 16 orphaned-FK / zero-qty /
  future-dated transactions are dropped during cleaning (Part 2) and logged in
  `output/cleaning_report.json`; they never reach the fact table.
- **Guest transactions** — kept with `customer_id` NULL and `is_guest = 1`;
  filtered out only by customer-level analytics (Part 4).

## Part 4 — Analytics

`src/analytics.py` answers the five business questions and writes
`output/analytics.json`. Run with `python -m src.analytics` (requires the
warehouse — run `python -m src.loader` first).

**Why SQL over pandas.** The data is already cleaned and modeled into a star
schema, so each question is a set-based aggregation over `fact_sales` joined to
its dimensions — SQL's core strength. Querying the warehouse also exercises the
model the way a downstream analyst/BI tool would, and keeps the business logic
declarative and auditable. Two derived values (MoM % change, the return-rate
flag) are computed in Python on top of the SQL aggregates, where guarded
division and nested output shaping read more clearly.

### Definitions & decisions

| Question | Definition used |
|---|---|
| **Q1 — Top 5 stores by net revenue (30d)** | Net revenue = `SUM(total_amount)` including returns (negative), over the 30 calendar days ending on the latest data date (2026-05-03 → 2026-06-01). |
| **Q2 — MoM revenue change % by category** | Net revenue per (category, month); `mom_change_pct = (m − m₋₁) / m₋₁ × 100`. Null for a category's first month or after a zero-revenue month. |
| **Q3 — Return rate by store** | `SUM(is_return) / COUNT(*)` per store; `high_return_rate = rate > 10%`. |
| **Q4 — Avg transaction value by region** | `AVG(total_amount)` per region, `WHERE is_return = 0`. |
| **Q5 — Top 10 customers by lifetime spend** | `SUM(total_amount)` net of returns, `WHERE is_guest = 0`; includes transaction count and AOV = spend / txn count. |

### Selected findings

- **Q1:** Southpark Meadows (S011) leads the trailing-30-day window at
  **$7,342.43**, followed by Galleria at Crystal Run and Eastview Mall.
- **Q3:** three stores exceed the 10% return-rate threshold and are flagged —
  **S015** (15.4%), **S006** (12.5%), **S008** (11.6%).
- **Q4:** average transaction value is fairly flat across regions
  (~$340–$397); "Unknown" is the two stores whose region was imputed in Part 2.
- **Q5:** top customer **CUST0213** spent **$3,077.96** over 4 transactions.

> **Caveat (Q2):** the data window ends on **2026-06-01**, so "June 2026" is a
> single day. Its steep MoM drop (≈ −96% to −99%) is a partial-period artifact,
> not a real trend — reported honestly rather than silently dropped. Categories
> with no sales on that day simply have no June row.

## Part 5 — Tests

`tests/test_pipeline.py` (run with `pytest`). Pytest config lives in
`pyproject.toml` (`pythonpath = ["."]` so `from src... import` resolves without
installing the package). Every test builds its own tiny, fully-known input and
asserts hand-computed expected values — no smoke tests.

| Area | Tests | Coverage |
|---|---|---|
| Profiling | 3 | Known counts / null % / numeric + date stats; **edge cases**: empty DataFrame and all-null column. |
| Cleaning | 3 | Zip zero-padding + `store_id` dedup + region imputation; multi-price → keep highest + zero-price flag; transaction currency parsing, `is_return`/`is_guest`/`price_mismatch` flags, and orphan/zero-qty/future exclusions. |
| Analytics | 1 | Loads a hand-built `CleanResult` into a temp SQLite warehouse and validates return rate (+flag), avg value by region (returns excluded), top customers (guests excluded), and net-revenue ranking. |

```bash
pytest            # 7 passed
```

## Part 6 — Productionizing This Pipeline

This is a batch pipeline over a static snapshot. Turning it into a
production system means addressing three things.

### Orchestration

Each stage is already a discrete, parameterized function with a clean boundary,
so it maps 1:1 onto tasks in an orchestrator (Airflow / Dagster / Prefect):

```
profile ──▶ clean ──▶ load ──▶ analytics
```

- **Trigger on data arrival**, not a wall clock — run when a new extract lands.
- **Pass the extract date in**, don't hardcode it. `clean_all(as_of_date=...)` is
  already a parameter (see the Reference date note); production would source it
  from the extract's metadata so "future-dated" is always relative to that pull.
- **Gate the DAG on quality** — treat the profiling/cleaning report as a
  checkpoint and fail (or quarantine) the run when thresholds are breached
  (e.g. null-rate spike, row-count drop, any orphan FK) rather than loading bad
  data.
- **Idempotent, retryable tasks** — a failed load should be safe to re-run.

### Incremental loads

The loader is currently **full-refresh** (drop and rebuild) — fine at this
scale, wrong at billions of rows. Production would:

- **Partition `fact_sales` by date** and load only the new/changed partitions
  from each extract, using an idempotent upsert keyed on `transaction_id` so
  re-runs don't double-count.
- **Extend, not rebuild, the dimensions.** `dim_date` grows forward. Store /
  product dimensions become **slowly-changing** — Type 1 for corrections,
  Type 2 (effective-dated rows) where history matters, e.g. a store changing
  region or a product's catalog price over time.
- **Late-arriving & out-of-order data** — handle extracts that backfill older
  dates without corrupting already-published aggregates.

### Observability

- **Emit the reports as metrics.** The profiling and cleaning JSON already
  quantify quality per run; ship those (row counts in/out per stage, null %,
  exclusion counts, return rate) to a monitoring system and alert on drift.
- **Data-quality tests as first-class checks** (Great Expectations / dbt tests)
  running in the DAG, not just unit tests in CI.
- **Lineage & structured run logs** — which extract produced which warehouse
  version, how many rows each stage dropped and why, run duration and status.
- **CI** — run `pytest` on every change; block merges on failure.

## What I'd Do Differently With More Time

- **Swap SQLite for a real analytical store** (DuckDB locally, or
  Postgres / Snowflake / BigQuery). SQLite is single-writer and perfect for a
  self-contained deliverable, but not for concurrent BI access or scale.
- **Layer the warehouse** raw → staging → marts (dbt-style) instead of one
  loader module, so transformations are versioned, tested, and documented as SQL.
- **Make cleaning rules declarative** — a config/registry of rules with
  externalized thresholds, rather than logic hardcoded per function, so a new
  data issue is a config change plus a test.
- **Close test gaps** — Q2 (month-over-month) is the most logic-heavy analytic
  and is currently unverified; I'd add a two-month fixture (including the
  zero-prior-month → null branch), an empty-warehouse edge case, and
  property-based tests for the currency/date parsers.
- **Effective-dated pricing** — if the source carried price dates, model
  multiple product prices as an SCD-2 dimension instead of collapsing to the
  highest catalog price.
- **Tooling** — add `mypy` and `ruff` to CI for type-safety and lint.
