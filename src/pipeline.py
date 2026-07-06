"""
pipeline.py  —  Mindex Data Engineer / Data Architect Code Challenge

Single end-to-end entrypoint that runs the whole pipeline in order and
regenerates every artifact under ``output/``:

    1. Profiling  (Part 1)  → output/profiling_report.json
    2. Cleaning   (Part 2)  → output/cleaning_report.json
    3. Modeling   (Part 3)  → output/warehouse.db
    4. Analytics  (Part 4)  → output/analytics.json

Each stage is delegated to its module's ``main()`` so the pipeline stays a thin
orchestrator — there is exactly one place that knows how to run each stage, and
running the pipeline produces byte-for-byte the same artifacts as running the
stages individually.

Usage:
    python -m src.pipeline
"""

from __future__ import annotations

from src import analytics, cleaner, loader, profiler

# (label, callable) for each stage, run in order.
STAGES = (
    ("Part 1 — Profiling", profiler.main),
    ("Part 2 — Cleaning", cleaner.main),
    ("Part 3 — Modeling", loader.main),
    ("Part 4 — Analytics", analytics.main),
)


def main() -> None:
    for label, run in STAGES:
        print(f"\n{'=' * 60}\n{label}\n{'=' * 60}")
        run()
    print(f"\n{'=' * 60}\nPipeline complete — all artifacts written to output/.\n{'=' * 60}")


if __name__ == "__main__":
    main()
