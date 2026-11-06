"""Load a docket into Postgres.

    python scripts/import_docket.py --demo 600            # synthetic demo docket
    python scripts/import_docket.py --json export.json    # list of case records (see README for fields)
    python scripts/import_docket.py --csv export.csv      # same fields as CSV columns; advocate_ids ';'-separated
"""
import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika import sample_data, store, triage  # noqa: E402

BOOL = {"accused_in_custody", "senior_citizen", "woman_or_child", "disability", "legal_aid", "first_time_offender"}
INT = {"adjournments"}


def from_csv(path):
    rows = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            rec = {k: v for k, v in r.items() if v not in ("", None)}
            for k in BOOL & rec.keys():
                rec[k] = str(rec[k]).strip().lower() in ("1", "true", "yes", "y")
            for k in INT & rec.keys():
                rec[k] = int(rec[k])
            if "advocate_ids" in rec:
                rec["advocate_ids"] = [a.strip() for a in rec["advocate_ids"].split(";") if a.strip()]
            rows.append(rec)
    return rows


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--demo", type=int)
    g.add_argument("--json")
    g.add_argument("--csv")
    args = ap.parse_args()
    cases = (sample_data.generate(args.demo) if args.demo else
             json.loads(Path(args.json).read_text(encoding="utf-8")) if args.json else from_csv(args.csv))
    store.prepare_database()
    n = store.upsert_cases(cases, {r["case_id"]: r for r in triage.triage_all(cases)},
                           source="synthetic" if args.demo else "csv")
    print(f"Loaded {n} cases")
