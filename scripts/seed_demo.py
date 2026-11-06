"""Seed the demo database with deterministic synthetic data (runs the migration first).

    python scripts/seed_demo.py --size 120 --seed 42 [--today 2026-10-26] [--url sqlite:///x.db]

Re-running replaces the previous synthetic rows; uploaded and imported cases are kept.
"""
import argparse
import json
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import demo_seed, store  # noqa: E402


def run(size: int = 120, seed: int = 42, today: date = None, url: str = None) -> dict:
    data = demo_seed.build(size, seed, today)
    with store.connect(url) as db:
        store.prepare_database(db)
        counts = demo_seed.write(db, data)
    counts["near_sec479_threshold"] = len(data["near_threshold"])
    counts["needs_review"] = len(data["needs_review"])
    counts["in_custody"] = sum(1 for c in data["cases"] if c.get("accused_in_custody"))
    return counts


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--size", type=int, default=120)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--today", type=date.fromisoformat, help="anchor date (default: today)")
    ap.add_argument("--url", help="database URL (default: DATABASE_URL)")
    a = ap.parse_args()
    print(json.dumps(run(a.size, a.seed, a.today, a.url), indent=2))
