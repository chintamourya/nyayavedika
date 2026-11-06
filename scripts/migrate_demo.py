"""Create / extend the demo schema. Idempotent: safe to run any number of times.

    python scripts/migrate_demo.py                      # uses DATABASE_URL (default sqlite:///nyayavedika_dev.db)
    python scripts/migrate_demo.py --url sqlite:///other.db

Also inserts missing reference rows (case_type_ref, stage_ref, statute_ref) and fills the promoted
cases columns for rows written by the older JSON-only path.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import store  # noqa: E402


def run(url: str = None) -> dict:
    with store.connect(url) as db:
        return store.prepare_database(db)


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="database URL (default: DATABASE_URL)")
    report = run(ap.parse_args().url)
    print(json.dumps({k: (len(v) if isinstance(v, list) else v) for k, v in report.items()}, indent=2))
