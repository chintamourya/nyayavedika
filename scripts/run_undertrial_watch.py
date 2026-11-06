"""Nightly Undertrial Watch run (cron / Windows Task Scheduler / k8s CronJob).

    python scripts/run_undertrial_watch.py [--court DEMO-DC]

Creates pending alerts with drafted release applications; a legal-aid lawyer approves them in the
UI (Undertrial Watch tab). The graph pauses at the approval step, so nothing is filed automatically.
"""
import argparse
import json
import sys
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika.agents import undertrial_watch  # noqa: E402

if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--court", default=None)
    args = ap.parse_args()
    out = undertrial_watch.graph().invoke({"court_id": args.court, "drafts": []},
                                          {"configurable": {"thread_id": f"watch-cron-{uuid.uuid4().hex[:8]}"}})
    print(json.dumps(out.get("summary"), indent=2, default=str))
