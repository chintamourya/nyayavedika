"""Scheduled jobs. No cron inside: run them from cron or the UI.

    python -m nyayavedika.jobs run undertrial_scan       # nightly 01:00 (and on custody-field changes)
    python -m nyayavedika.jobs run aging_update          # nightly: SLA dates, aging boost, must-list, past deadline
    python -m nyayavedika.jobs run weekly_cause_list     # Friday: draft next week's list (Registrar approves)
    python -m nyayavedika.jobs run daily_topup           # mornings: new Critical / release-eligible cases into the open draft

Each run writes an agent_runs row (start, end, counts, error) so a missed night is visible.
"""
import argparse
import json
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Callable, Dict, Optional

from . import cause_list, config, scheduler, store  # config reads .env on import

logger = logging.getLogger("nyayavedika.jobs")


def undertrial_scan(db, today: date) -> Dict:
    from .agents import undertrial_watch
    rescored = cause_list.rescore_custody(db, today)   # keep stored bands / flags in step with the days in custody
    out = undertrial_watch.run_scan(db, today=today)
    return {"rescored_custody_cases": rescored, "new_release_alerts": out["new_release_alerts"], "approaching": out["approaching_threshold"],
            "data_needed": len(out["data_needed"])}


def aging_update(db, today: date) -> Dict:
    """SLA date per band (tightened when the band rises), aging boost and must-list for every pending case."""
    states = {r["case_id"]: r for r in db.select("case_queue_state")}
    rows, past, must = [], 0, 0
    for c in db.select("cases", {"status": "pending"}):
        st = states.get(c["case_id"], {})
        sla_new = scheduler.add_working_days(today, int(config.SLA_DAYS.get(c["band"] or "Routine", 30))).isoformat()
        sla = min(st["sla_due_on"], sla_new) if st.get("sla_due_on") else sla_new
        pr = scheduler.effective_priority(c["score"] or 0, c["band"] or "Routine", {**st, "sla_due_on": sla}, today)
        past += pr["past_deadline"]
        must += pr["must_list"]
        rows.append({"case_id": c["case_id"], "first_eligible_on": st.get("first_eligible_on") or today.isoformat(),
                     "sla_due_on": sla, "aging_boost": pr["aging_boost"], "must_list": pr["must_list"],
                     "needs_review": c["data_quality"] == "needs_review"})
    store.upsert_queue_state(rows, db=db)
    return {"cases": len(rows), "past_deadline": past, "must_list": must}


def weekly_cause_list(db, today: date) -> Dict:
    start = today + timedelta(days=(7 - today.weekday()) % 7 or 7)  # next Monday
    plan = cause_list.prepare(db, start, 5)
    cid = cause_list.save_draft(db, plan, explanation="Weekly draft (job) - awaiting Registrar approval")
    m = plan["metrics"]
    return {"cause_list_id": cid, "start_date": start.isoformat(), "listed": m["cases_listed"],
            "carried_over": m["cases_carried_over"], "utilisation": m["avg_bench_utilisation_percent"],
            "capacity_shortfall": bool(plan["capacity_shortfall"]), "violations": len(plan["violations"])}


def daily_topup(db, today: date) -> Dict:
    cause_list.score_changed(db, today)
    cause_list.rescore_custody(db, today)
    slots = []
    for c in db.select("cases", {"status": "pending"}):
        if c["band"] == "Critical" or "UNDERTRIAL_RELEASE_ELIGIBLE" in (c["flags"] or []):
            slot = cause_list.fast_lane(db, c["case_id"], today)
            if slot:
                slots.append(slot["case_id"])
    return {"in_open_draft": len(slots)}


JOBS: Dict[str, Callable] = {"undertrial_scan": undertrial_scan, "aging_update": aging_update,
                             "weekly_cause_list": weekly_cause_list, "daily_topup": daily_topup}


def run(name: str, today: Optional[date] = None) -> Dict:
    if name not in JOBS:
        raise KeyError(f"Unknown job {name}; choose from {', '.join(JOBS)}")
    today = today or date.today()
    with store.connect() as db:
        store.prepare_database(db)
        store.load_reference_into_triage(db)
        run_id = db.insert("agent_runs", [{"job": name, "started": datetime.now(timezone.utc)}], returning="id")
        db.commit()
        try:
            counts = JOBS[name](db, today)
            db.update("agent_runs", {"id": run_id}, {"ended": datetime.now(timezone.utc), "counts": counts})
            db.commit()
            return {"job": name, "run_id": run_id, **counts}
        except Exception as exc:
            db.rollback()
            db.update("agent_runs", {"id": run_id}, {"ended": datetime.now(timezone.utc), "error": str(exc)[:500]})
            db.commit()
            raise


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="NyayaVedika scheduled jobs")
    ap.add_argument("command", choices=["run"])
    ap.add_argument("job", choices=sorted(JOBS))
    ap.add_argument("--today", type=date.fromisoformat, default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    print(json.dumps(run(args.job, args.today), indent=2, default=str))


if __name__ == "__main__":
    main()
