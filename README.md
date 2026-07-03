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
