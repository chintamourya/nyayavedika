"""Compute pilot metrics from a CSV log and write a markdown table for the submission.

    python scripts/pilot_report.py pilot/pilot_log.csv --write docs/PILOT_RESULTS.md

Columns are described in nyayavedika/pilot_metrics.py. Use anonymised case references only.
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika import pilot_metrics  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("csv")
    ap.add_argument("--write")
    a = ap.parse_args()
    text = pilot_metrics.to_markdown(pilot_metrics.summarise(pilot_metrics.read_csv(a.csv)), source=a.csv)
    print(text)
    if a.write:
        Path(a.write).write_text(text, encoding="utf-8")
        print(f"Wrote {a.write}")
