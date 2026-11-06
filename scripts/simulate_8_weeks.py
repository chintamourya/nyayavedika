"""8-week rolling simulation (SYNTHETIC data): weekly cause lists with and without aging / must-list.

    python scripts/simulate_8_weeks.py [--initial 1500 --weekly 700 --weeks 8 --seed 42] [--write docs/SIMULATION.md]

Model (deliberately simple, stated in the output):
  * week 0 docket = sample_data.generate(initial); every week `weekly` new filings arrive (same generator, new seed)
  * a case's deadline clock starts the week it joins the queue: SLA working days by band (config.SLA_DAYS)
  * each week scheduler.plan_week lists cases for 5 working days; a listed case leaves the queue
    (its next listing is a new event); an unlisted case is deferred (consecutive_deferrals + 1)
  * "with aging": score_eff boost + must-list in the reserved share; "without": plain priority, no reserve
Reports longest wait per band, share of cases deferred 3+ times, cases past deadline, utilisation.
"""
import argparse
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, sample_data, scheduler, triage  # noqa: E402

BANDS = ("Critical", "High", "Medium", "Routine")


def run(initial: int, weekly: int, weeks: int, seed: int, aging: bool, start: date) -> dict:
    pending, state, entered_band = {}, {}, {}
    waits = {b: [] for b in BANDS}
    deferred_counts, late, util = {}, set(), []

    def admit(cases, week_start):
        for c in triage.triage_all(cases, week_start):
            pending[c["case_id"]] = c["case"]
            entered_band[c["case_id"]] = c["band"]
            state[c["case_id"]] = {"first_eligible_on": week_start.isoformat(), "consecutive_deferrals": 0,
                                   "sla_due_on": scheduler.add_working_days(week_start, config.SLA_DAYS[c["band"]]).isoformat()}

    admit(sample_data.generate(initial, seed=seed, today=start), start)
    for w in range(weeks):
        week_start = start + timedelta(weeks=w)
        if w:
            new = sample_data.generate(weekly, seed=seed * 1000 + w, today=week_start)
            for c in new:
                c["case_id"] = f"W{w}-{c['case_id']}"
            admit(new, week_start)
        results = triage.triage_all(list(pending.values()), week_start)
        plan = scheduler.plan_week(results, week_start, 5, state=state, aging=aging, reserve=None if aging else 0.0)
        util.append(plan["metrics"]["avg_bench_utilisation_percent"])
        for d in plan["calendar"]:
            for b in d["benches"]:
                for c in b["cases"]:
                    st = state[c["case_id"]]
                    waited = (date.fromisoformat(d["date"]) - date.fromisoformat(st["first_eligible_on"])).days
                    waits[entered_band[c["case_id"]]].append(waited)
                    if d["date"] > st["sla_due_on"]:
                        late.add(c["case_id"])
                    del pending[c["case_id"]]
        for u in plan["unscheduled"]:
            st = state[u["case_id"]]
            st["consecutive_deferrals"] += 1
            deferred_counts[u["case_id"]] = st["consecutive_deferrals"]
    end = start + timedelta(weeks=weeks)
    for cid in pending:  # still waiting at the end: their wait so far counts, and so does a passed deadline
        st = state[cid]
        waits[entered_band[cid]].append((end - date.fromisoformat(st["first_eligible_on"])).days)
        if end.isoformat() > st["sla_due_on"]:
            late.add(cid)
    seen = len(state)
    return {"aging": aging, "cases_seen": seen, "still_waiting": len(pending),
            "longest_wait_days": {b: max(waits[b]) if waits[b] else 0 for b in BANDS},
            "deferred_3_plus_percent": round(100 * sum(1 for v in deferred_counts.values() if v >= 3) / seen, 1),
            "past_deadline": len(late), "avg_utilisation_percent": round(sum(util) / len(util), 1)}


def report(args) -> str:
    start = date.fromisoformat(args.start)
    rows = [run(args.initial, args.weekly, args.weeks, args.seed, aging, start) for aging in (True, False)]
    lines = ["# 8-week simulation (SYNTHETIC data - not court results)", "",
             f"Command: `python scripts/simulate_8_weeks.py --initial {args.initial} --weekly {args.weekly} "
             f"--weeks {args.weeks} --seed {args.seed} --start {args.start}`; rules {triage.RULES_VERSION}; "
             f"SLA working days {config.SLA_DAYS}; must-list after {config.MUST_LIST_AFTER_DEFERRALS} deferrals; "
             f"reserve {int(config.MUST_LIST_RESERVE * 100)}%; aging cap {config.AGING_CAP}.", "",
             "| | With aging + must-list | Without (plain priority) |", "|---|---|---|"]
    a, b = rows
    for label, key in (("Cases seen", "cases_seen"), ("Still waiting at the end", "still_waiting"),
                       ("Cases past deadline", "past_deadline"), ("Share deferred 3+ times (%)", "deferred_3_plus_percent"),
                       ("Average utilisation (%)", "avg_utilisation_percent")):
        lines.append(f"| {label} | {a[key]} | {b[key]} |")
    for band in BANDS:
        lines.append(f"| Longest wait, {band} (days) | {a['longest_wait_days'][band]} | {b['longest_wait_days'][band]} |")
    lines += ["", "Model: listed cases leave the queue; unlisted ones are deferred; deadline clocks start when a case joins;",
              "new filings every week from the same synthetic generator. It shows starvation and its fix, not real court",
              "throughput. 5 benches x 300 minutes x 5 days per week, expected minutes sized by adjournment risk."]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--initial", type=int, default=1500)
    ap.add_argument("--weekly", type=int, default=700)  # near capacity: where starvation shows
    ap.add_argument("--weeks", type=int, default=8)
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--start", default="2026-11-02")
    ap.add_argument("--write", help="also write the report to this file (e.g. docs/SIMULATION.md)")
    args = ap.parse_args()
    text = report(args)
    print(text)
    if args.write:
        Path(args.write).write_text(text, encoding="utf-8")
