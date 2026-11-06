"""Load or export the Act / section / maximum-sentence table (statute_ref).

    python scripts/import_statutes.py --export data/statutes_template.csv   # current rows -> CSV to edit
    python scripts/import_statutes.py --csv data/statutes_verified.csv --dry-run   # check only
    python scripts/import_statutes.py --csv data/statutes_verified.csv             # load / update rows

Existing rows with the same act + section are replaced, so a lawyer-verified row overwrites the demo row.
See nyayavedika/statute_import.py for the CSV columns. Add rows from the bare Acts (indiacode.nic.in) and have a lawyer verify them.
"""
import argparse
import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika import statute_import  # noqa: E402


def export(path: str) -> int:
    from nyayavedika import reference_data
    rows = reference_data.STATUTES
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(statute_import.COLUMNS)
        for act, section, offence, years, life, bailable, compoundable in rows:
            w.writerow([act, section, offence, "" if life else years, "yes" if life else "no",
                        "yes" if bailable else "no", "yes" if compoundable else "no", "", ""])
    return len(rows)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--csv")
    g.add_argument("--export")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    if a.export:
        print(f"Wrote {export(a.export)} rows to {a.export} (verified_by and source are empty: fill them as you check each row)")
        sys.exit(0)
    rows, problems = statute_import.read_csv(a.csv)
    for p in problems:
        print("PROBLEM:", p)
    unverified = sum(1 for r in rows if r["note"] == "UNVERIFIED")
    print(f"{len(rows)} valid rows, {len(problems)} problems, {unverified} unverified")
    if a.dry_run or problems and not rows:
        sys.exit(1 if problems else 0)
    from nyayavedika import store
    store.prepare_database()
    with store._session(None) as s:
        s.upsert("statute_ref", rows, ["act", "section"], update=True)
    print(f"Loaded {len(rows)} rows into statute_ref" + (" (problem rows were skipped)" if problems else ""))
