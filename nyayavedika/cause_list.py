"""Cause lists with memory: the database side of nyayavedika.scheduler.plan_week.

    prepare()      score only changed cases, read pending cases + case_queue_state + calendar, plan, check invariants
    save_draft()   cause_lists + listings rows, a deferrals row (with reason) per case left out, queue state updated
    publish()      Registrar approval only: hearings rows, next_hearing_date, listings 'published', audit_log
    fast_lane()    a new Critical / release-eligible case gets a proposed slot in the nearest open draft list
    accept_slot()  Registrar accepts, moves or holds a proposed slot
    record_outcome() heard / adjourned / disposed / not_reached -> learned adjournment rates (k = 10 smoothing)

Three events stay apart: deferred by the scheduler (deferrals), adjourned in court (hearings), on hold (hold_until).
Nothing here publishes on its own; /api/schedule remains a draft-only preview.
"""
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Dict, List, Optional

from . import config, extraction, impact, scheduler, staff_api, store, triage

logger = logging.getLogger(__name__)
SMOOTHING_K = config.SMOOTHING_K
OPEN_LISTING = ("planned", "proposed", "accepted")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


# ----------------------------------------------------------------------------- inputs
def load_benches(db) -> List[Dict]:
    rows = db.select("benches", {"active": True}, order="bench_id")
    return [{"bench_id": r["bench_id"], "name": r["name"], "case_types": r["case_types"] or ["*"],
             "minutes_per_day": r["minutes_per_day"] or 300} for r in rows] or scheduler.DEFAULT_BENCHES


def calendar_rows(db, start: date, days: int) -> List[Dict]:
    end = scheduler.add_working_days(start, days + 10).isoformat()
    return [r for r in db.select("court_calendar") if start.isoformat() <= r["day"] <= end]


def learned_rates(db) -> Dict:
    """p_adj = (adjourned + k*prior) / (listed + k) per (case_type, stage), from recorded hearings."""
    rows = db.query("""SELECT c.case_type AS case_type, c.stage AS stage,
                              SUM(CASE WHEN h.outcome IN ('adjourned', 'not_reached') THEN 1 ELSE 0 END) AS adjourned,
                              COUNT(*) AS listed
                       FROM hearings h JOIN cases c ON c.case_id = h.case_id
                       WHERE h.outcome IS NOT NULL GROUP BY c.case_type, c.stage""")
    rates = {}
    for r in rows:
        prior = triage.STAGE_ADJ_RISK.get(r["stage"] or "", 0.4)
        rates[(r["case_type"], r["stage"])] = round((r["adjourned"] + SMOOTHING_K * prior) / (r["listed"] + SMOOTHING_K), 3)
    return rates


def score_changed(db, today: Optional[date] = None) -> int:
    """Re-score only cases edited since their last triage_scores row (or never scored)."""
    today = today or date.today()
    rows = db.query("""SELECT case_id FROM cases c WHERE c.status IN ('pending', 'on_hold') AND (c.score IS NULL OR NOT EXISTS
                         (SELECT 1 FROM triage_scores t WHERE t.case_id = c.case_id AND t.scored_at >= c.updated_at))""")
    if not rows:
        return 0
    states = {r["case_id"]: r for r in db.select("case_queue_state")}
    cases = store.get_cases([r["case_id"] for r in rows], db=db)   # one query, not one per case
    _rescore_and_save(db, [cases[r["case_id"]] for r in rows if r["case_id"] in cases], states, today)
    db.commit()
    return len(rows)


def _rescore_and_save(db, cases: List[Dict], states: Dict[str, Dict], today: date) -> List[Dict]:
    """Score each case with the deterministic rules and write the rows + triage history in batched statements
    (a remote Postgres pays one round trip per statement, so per-case writes made a full re-score take minutes)."""
    rows, scores = [], []
    for case in cases:
        probe = {**case, "first_eligible_on": (states.get(case["case_id"]) or {}).get("first_eligible_on")}
        scored = extraction.provisional_score(probe, today)
        meta = {k: case.get(k) for k in ("source", "data_quality", "field_provenance")}
        clean = {k: v for k, v in case.items() if not k.startswith("_") and k not in meta}
        rows.append(store.case_row(clean, scored, meta["source"], meta["data_quality"], meta["field_provenance"]))
        scores.append(scored)
    if rows:
        db.upsert("cases", rows, ["case_id"])
        store.insert_triage_scores(scores, triage.RULES_VERSION, db=db)
    return scores


def rescore_custody(db, today: Optional[date] = None) -> int:
    """Custody cases cross the Sec. 479 marks as days pass without any edit, so their stored score / band / flags
    must be refreshed daily; otherwise Today, the Docket and the planner disagree with the Undertrial watch."""
    today = today or date.today()
    states = {r["case_id"]: r for r in db.select("case_queue_state")}
    stale = []
    # only custody cases can cross a Sec. 479 mark by the calendar alone; the row already carries the case JSON,
    # so no per-case SELECT is needed
    for row in db.select("cases", {"status": ["pending", "on_hold"]}):
        case = store._case_out(row)
        if not case.get("accused_in_custody") or not case.get("custody_since"):
            continue
        probe = {**case, "first_eligible_on": (states.get(row["case_id"]) or {}).get("first_eligible_on")}
        scored = extraction.provisional_score(probe, today)
        if scored["band"] == row["band"] and sorted(scored["flags"]) == sorted(row["flags"] or []):
            continue
        stale.append(case)
    _rescore_and_save(db, stale, states, today)
    db.commit()
    return len(stale)


def pending_results(db, court_id: Optional[str] = None) -> List[Dict]:
    """Planner input from the stored score / band / flags (no full re-triage of the docket)."""
    where = {"status": ["pending", "on_hold"], **({"court_id": court_id} if court_id else {})}
    out = []
    for row in db.select("cases", where, order="case_id"):
        case = {**(row["data"] or {}), "status": row["status"]}
        flags = row["flags"] or []
        out.append({"case_id": row["case_id"], "score": row["score"] or 0.0, "band": row["band"] or "Routine", "flags": flags,
                    "reasons": [], "recommended_route": row["route"] or "Regular list", "case": case,
                    "estimated_minutes": triage.estimated_minutes(case), "adjournment_risk": triage.adjournment_risk(case),
                    "needs_review": row["data_quality"] == "needs_review" or "CUSTODY_DATE_MISSING" in flags})
    return out


FIRM_LISTING = ("planned", "accepted", "published")   # a slot the case already holds; a fast-lane 'proposed' is not firm


def already_listed(db, start: date, days: int, calendar: Optional[List[Dict]] = None) -> Dict[str, Dict]:
    """Cases that already hold a firm slot inside the week being planned, on another list: an accepted fast-lane slot,
    a published list, or another open draft whose dates overlap. The open weekly draft for the same Monday is ignored
    because save_draft supersedes it. Listing these again would schedule the same case twice."""
    calendar = calendar if calendar is not None else calendar_rows(db, start, days)
    closed = sorted({c["day"] for c in calendar if c["kind"] in scheduler.CLOSED_KINDS and not c.get("bench_id")})
    window = [d.isoformat() for d in scheduler.working_days(start, days, closed)]
    if not window:
        return {}
    lists = {c["id"]: c for c in db.select("cause_lists", {"status": ["draft", "published"]})}
    replaced = {i for i, c in lists.items() if c["status"] == "draft" and c["start_date"] == start.isoformat()
                and not (c["plan"] or {}).get("fast_lane")}
    out: Dict[str, Dict] = {}
    for l in db.select("listings", {"status": list(FIRM_LISTING)}, order="day"):
        if l["cause_list_id"] in replaced or l["cause_list_id"] not in lists or not (window[0] <= l["day"] <= window[-1]):
            continue
        out.setdefault(l["case_id"], {"day": l["day"], "bench_id": l["bench_id"], "slot": f"{l['slot_start']}-{l['slot_end']}",
                                      "listing_status": l["status"], "cause_list_id": l["cause_list_id"]})
    return out


def prepare(db, start: date, days: int = 5, court_id: Optional[str] = None, aging: bool = True,
            results: Optional[List[Dict]] = None) -> Dict:
    """`results` lets the Registry Agent pass scores after its bounded AI review; otherwise they are read here."""
    rescored = 0
    if results is None:
        rescored = score_changed(db, date.today())  # scores are facts as of today, not the draft's Monday
        triage.load_adjournment_rates(learned_rates(db))
        results = pending_results(db, court_id)
    state = {r["case_id"]: r for r in db.select("case_queue_state")}
    calendar = calendar_rows(db, start, days)
    plan = scheduler.plan_week(results, start, days, load_benches(db), state, calendar,
                               aging=aging, rules_version=triage.RULES_VERSION,
                               already_listed=already_listed(db, start, days, calendar))
    plan["violations"] += [v for v in scheduler.check_plan(plan, {r["case_id"] for r in results}) if v not in plan["violations"]]
    plan["metrics"]["rescored"] = rescored
    sources = staff_api.case_sources(db)   # so the screen can mark synthetic vs uploaded cases
    for d in plan["calendar"]:
        for b in d["benches"]:
            for c in b["cases"]:
                c["source"] = sources.get(c["case_id"])
    for u in plan["unscheduled"] + plan.get("already_listed", []):
        u["source"] = sources.get(u["case_id"])
    return plan


# ----------------------------------------------------------------------------- before drafting: will the week fit?
def preview(db, start: date, days: int = 5) -> Dict:
    """What a draft for this week would face, before anything is saved: bench time available (calendar closures and
    judges on leave removed) against the expected time of the cases waiting to be listed, using the same
    eligibility, hold, must-list and expected-minutes rules as the planner. Read-only; an estimate, not a plan."""
    days = max(1, min(int(days or 5), 10))
    results = pending_results(db)
    state = {r["case_id"]: r for r in db.select("case_queue_state")}
    # prepare() re-scores edited / never-scored cases before planning; do the same here, in memory only, so the
    # preview and the draft agree (a GET must not write)
    stale = {r["case_id"] for r in db.query(
        """SELECT case_id FROM cases c WHERE c.status IN ('pending', 'on_hold') AND (c.score IS NULL OR NOT EXISTS
             (SELECT 1 FROM triage_scores t WHERE t.case_id = c.case_id AND t.scored_at >= c.updated_at))""")}
    if stale:
        fresh = store.get_cases(stale, db=db)
        for r in results:
            if r["case_id"] in fresh:
                case = fresh[r["case_id"]]
                probe = {**case, "first_eligible_on": (state.get(r["case_id"]) or {}).get("first_eligible_on")}
                s = extraction.provisional_score(probe, date.today())
                r.update(score=s["score"], band=s["band"], flags=s["flags"])
    calendar = calendar_rows(db, start, days)
    closed = sorted({c["day"] for c in calendar if c["kind"] in scheduler.CLOSED_KINDS and not c.get("bench_id")})
    leave = {(c["day"], c["bench_id"]) for c in calendar if c.get("bench_id")}
    benches = load_benches(db)
    day_list = scheduler.working_days(start, days, closed)
    sittings = [(d.isoformat(), b) for d in day_list for b in benches if (d.isoformat(), b["bench_id"]) not in leave]
    capacity = sum(b["minutes_per_day"] for _, b in sittings)
    elsewhere = already_listed(db, start, days, calendar)
    by_band = {b: 0 for b in staff_api.BANDS}
    waiting, held, must, past, custody, minutes, must_minutes = 0, 0, 0, 0, 0, 0.0, 0.0
    for r in results:
        st = state.get(r["case_id"], {})
        if r["case_id"] in elsewhere:
            continue
        hold = st.get("hold_until")
        if r["case"].get("status") == "on_hold" or (hold and hold > start.isoformat()):
            held += 1
            continue
        pr = scheduler.effective_priority(r["score"], r["band"], st, start)
        is_must = pr["must_list"] or r["band"] == "Critical" or "UNDERTRIAL_RELEASE_ELIGIBLE" in r["flags"]
        need = scheduler._expected_minutes(r)
        waiting += 1
        minutes += need
        by_band[r["band"]] = by_band.get(r["band"], 0) + 1
        if is_must:
            must += 1
            must_minutes += need
        past += 1 if pr["past_deadline"] else 0
        custody += 1 if r["case"].get("accused_in_custody") else 0
    reserve = capacity * config.MUST_LIST_RESERVE
    if not capacity:
        verdict = "No bench sits on these days (holidays or leave in the court calendar)."
    elif minutes <= capacity:
        verdict = "Every waiting case is expected to fit in this week's bench time."
    else:
        verdict = (f"About {round(100 * capacity / minutes)}% of the waiting work fits; the rest is carried over and "
                   "climbs next week (must-list cases go first).")
    last = day_list[-1].isoformat() if day_list else start.isoformat()
    return {"start_date": start.isoformat(), "days": [d.isoformat() for d in day_list],
            "closed_days": [d for d in closed if start.isoformat() <= d <= last],   # only the planned week
            "benches": len(benches), "sittings": len(sittings), "benches_on_leave": len(leave),
            "capacity_minutes": round(capacity), "waiting": waiting, "waiting_minutes": round(minutes),
            "by_band": by_band, "must_list": must, "must_list_minutes": round(must_minutes),
            "must_list_reserve_minutes": round(reserve), "must_list_over_reserve": must_minutes > reserve,
            "past_deadline": past, "in_custody": custody, "on_hold": held, "already_listed": len(elsewhere),
            "fits": bool(capacity) and minutes <= capacity, "verdict": verdict,
            "note": "Expected minutes allow for each case's likely adjournment; the draft itself also checks advocate clashes."}


# ----------------------------------------------------------------------------- read a saved list back
def recent(db, limit: int = 12) -> Dict:
    """Recent cause lists (weekly drafts, fast-lane drafts, published), newest first, so the screen can reopen one."""
    rows = db.select("cause_lists", order="id DESC", limit=int(max(1, min(limit, 50))))
    counts: Dict[int, int] = {}
    if rows:
        for l in db.select("listings", {"cause_list_id": [r["id"] for r in rows],
                                        "status": list(OPEN_LISTING) + ["published", "heard", "adjourned"]}):
            counts[l["cause_list_id"]] = counts.get(l["cause_list_id"], 0) + 1
    keep = ("id", "status", "start_date", "created_at", "approved_by", "decided_at")
    return {"lists": [{**{k: r.get(k) for k in keep}, "fast_lane": bool((r.get("plan") or {}).get("fast_lane")),
                       "cases": counts.get(r["id"], 0)} for r in rows]}


def view(db, cause_list_id: int) -> Dict:
    """A saved list in the same shape as a freshly prepared draft, with each bench's cases rebuilt from the listings
    as they stand now (moves, holds and accepted fast-lane slots included), plus readiness notes. Read-only."""
    rows = db.select("cause_lists", {"id": cause_list_id})
    if not rows:
        raise LookupError(f"No cause list {cause_list_id}")
    cl = rows[0]
    plan = cl["plan"] or {}
    live = ("published", "heard", "adjourned") if cl["status"] == "published" else OPEN_LISTING
    listings = [l for l in db.select("listings", {"cause_list_id": cause_list_id}, order="day, bench_id, slot_start")
                if l["status"] in live]
    planned = {c["case_id"]: c for d in plan.get("calendar") or [] for b in d["benches"] for c in b["cases"]}
    benches = {b["bench_id"]: b for b in load_benches(db)}
    sources = staff_api.case_sources(db)
    calendar = [{**d, "benches": [{**b, "cases": []} for b in d["benches"]]} for d in plan.get("calendar") or []]
    by_day = {d["date"]: d for d in calendar}
    for l in listings:
        day = by_day.get(l["day"])
        if day is None:   # a fast-lane list has no planned calendar: build the day as listings arrive
            day = by_day[l["day"]] = {"date": l["day"], "benches": []}
            calendar.append(day)
        bench = next((b for b in day["benches"] if b["bench_id"] == l["bench_id"]), None)
        if bench is None:
            meta = benches.get(l["bench_id"], {})
            bench = {"bench_id": l["bench_id"], "name": meta.get("name", l["bench_id"]), "open": True,
                     "minutes_per_day": meta.get("minutes_per_day", 300), "cases": []}
            day["benches"].append(bench)
        base = planned.get(l["case_id"], {})
        bench["cases"].append({**base, "case_id": l["case_id"], "band": l["band"] or base.get("band"),
                               "score": l["score"] if l["score"] is not None else base.get("score"),
                               "slot": f"{l['slot_start']}-{l['slot_end']}", "expected_minutes": l["expected_minutes"] or 0,
                               "listing_status": l["status"], "source": sources.get(l["case_id"])})
    calendar.sort(key=lambda d: d["date"])
    for d in calendar:
        for b in d["benches"]:
            used = sum(c.get("expected_minutes") or 0 for c in b["cases"])
            cap = b.get("minutes_per_day") or 0
            b["expected_minutes"] = round(used)
            b["utilisation_percent"] = round(100 * used / cap, 1) if cap else 0.0
            b["cases"].sort(key=lambda c: c["slot"])
    listed_ids = {c["case_id"] for d in calendar for b in d["benches"] for c in b["cases"]}
    util = [b["utilisation_percent"] for d in calendar for b in d["benches"] if b.get("open", True)]
    metrics = {**(cl["metrics"] or {}), "cases_listed": len(listed_ids)}
    if util:
        metrics["avg_bench_utilisation_percent"] = round(sum(util) / len(util), 1)
    for key in ("must_list_listed", "must_list_total", "cases_carried_over"):
        metrics.setdefault(key, 0)
    for u in plan.get("unscheduled") or []:
        u.setdefault("source", sources.get(u["case_id"]))
    return {"cause_list_id": cl["id"], "status": cl["status"], "start_date": cl["start_date"],
            "fast_lane": bool(plan.get("fast_lane")), "approved_by": cl.get("approved_by"),
            "metrics": metrics, "violations": plan.get("violations") or [],
            "capacity_shortfall": plan.get("capacity_shortfall"), "deadline_alerts": plan.get("deadline_alerts") or [],
            "unscheduled": [u for u in (plan.get("unscheduled") or []) if u["case_id"] not in listed_ids][:200],
            "already_listed": (plan.get("already_listed") or [])[:200], "calendar": calendar,
            "readiness": staff_api.readiness(db, listed_ids)}


# ----------------------------------------------------------------------------- write a draft
def _sla_due(band: str, anchor: date) -> str:
    return scheduler.add_working_days(anchor, int(config.SLA_DAYS.get(band, 30))).isoformat()


def save_draft(db, plan: Dict, court_id: str = "DEMO-DC", explanation: str = "") -> int:
    """Store the draft and its planned listings. Queue counters (deferrals, must-list) change only when a list is
    published, so preparing several drafts does not make cases look deferred. An older open draft for the same week
    is superseded (its slots are dropped), so Accept / Move / Hold always act on the list on screen."""
    for old in db.select("cause_lists", {"status": "draft", "start_date": plan["start_date"]}):
        if not (old["plan"] or {}).get("fast_lane"):
            db.update("listings", {"cause_list_id": old["id"], "status": list(OPEN_LISTING)}, {"status": "dropped"})
            db.update("cause_lists", {"id": old["id"]}, {"status": "superseded", "decided_at": _now()})
    cid = db.insert("cause_lists", [{"court_id": court_id, "start_date": plan["start_date"], "plan": plan,
                                     "metrics": plan["metrics"], "explanation": explanation, "status": "draft",
                                     "created_at": _now()}], returning="id")
    listed = {}
    rows = []
    for d in plan["calendar"]:
        for b in d["benches"]:
            for c in b["cases"]:
                listed[c["case_id"]] = d["date"]
                rows.append({"cause_list_id": cid, "case_id": c["case_id"], "day": d["date"], "bench_id": b["bench_id"],
                             "slot_start": c["slot"].split("-")[0], "slot_end": c["slot"].split("-")[1],
                             "expected_minutes": int(round(c["expected_minutes"])), "band": c["band"], "score": c["score"],
                             "status": "planned"})
    db.insert("listings", rows)
    # a fast-lane proposal (not yet accepted) for a case this draft now lists in the same week would become a second
    # hearing if accepted later: the weekly slot takes over and the proposal is withdrawn
    days = sorted({d["date"] for d in plan["calendar"]})
    ids = sorted(listed)
    for i in range(0, len(ids) if days else 0, 500):
        stale = [l["id"] for l in db.select("listings", {"case_id": ids[i:i + 500], "status": "proposed"})
                 if l["cause_list_id"] != cid and days[0] <= l["day"] <= days[-1]]
        if stale:
            db.update("listings", {"id": stale}, {"status": "dropped"})
    db.commit()
    return cid


def _apply_queue(db, plan: Dict, cid: int, listed_ids: set) -> None:
    """On publish: cases on the list reset their deferral counter; cases left out are deferred +1 (with the reason)."""
    start = date.fromisoformat(plan["start_date"])
    deferred = {u["case_id"]: u for u in plan.get("unscheduled") or [] if u["case_id"] not in listed_ids}
    held = {r["case_id"] for r in db.select("listings", {"cause_list_id": cid, "status": "dropped"})} - listed_ids
    db.insert("deferrals", [{"case_id": u["case_id"], "cause_list_id": cid, "run_at": _now(), "reason": u["reason"],
                             "score": u["score"], "band": u["band"]} for u in deferred.values()])
    states = {r["case_id"]: r for r in db.select("case_queue_state")}
    bands = {u["case_id"]: u["band"] for u in deferred.values()}
    bands.update({c["case_id"]: c["band"] for d in plan["calendar"] for b in d["benches"] for c in b["cases"]
                  if c["case_id"] in listed_ids})
    updates = []
    for case_id, band in bands.items():
        if case_id in held:
            continue  # put on hold by the Registrar: the hold applies, not a deferral
        st = states.get(case_id, {})
        row = {"case_id": case_id, "times_considered": (st.get("times_considered") or 0) + 1,
               "first_eligible_on": st.get("first_eligible_on") or start.isoformat(),
               "sla_due_on": st.get("sla_due_on") or _sla_due(band, start)}
        if case_id in deferred:
            u = deferred[case_id]
            consecutive = (st.get("consecutive_deferrals") or 0) + 1
            row.update(times_deferred=(st.get("times_deferred") or 0) + 1, consecutive_deferrals=consecutive,
                       last_deferral_reason=u["reason"])
        else:
            row.update(consecutive_deferrals=0)  # listed: the counter resets
        pr = scheduler.effective_priority(0, band, {**st, **row}, start)
        row.update(aging_boost=pr["aging_boost"], must_list=pr["must_list"])
        updates.append(row)
    store.upsert_queue_state(updates, db=db)


# ----------------------------------------------------------------------------- human gate: publish / reject
def _draft(db, cause_list_id: int) -> Dict:
    rows = db.select("cause_lists", {"id": cause_list_id})
    if not rows:
        raise LookupError(f"No cause list {cause_list_id}")
    if rows[0]["status"] != "draft":
        raise ValueError(f"Cause list {cause_list_id} is {rows[0]['status']}, not a draft")
    return rows[0]


def _longer_statement_timeout(db, ms: int = config.DB_STATEMENT_TIMEOUT_MS) -> None:
    """Postgres only: publishing writes many rows in one transaction, so allow it more than a hosted database's default
    per-statement limit. SET LOCAL ends with the transaction. Other databases (SQLite dev) are left alone."""
    if not str(config.DATABASE_URL or "").startswith("postgres"):
        return
    try:
        db.execute(f"SET LOCAL statement_timeout = {int(ms)}")
    except Exception as exc:   # never block a publish on a tuning knob
        logger.warning("could not raise statement_timeout: %s", exc)


def publish(db, cause_list_id: int, actor: str, role: str) -> Dict:
    draft = _draft(db, cause_list_id)
    # fast-lane proposals become hearings only once the Registrar has accepted them
    listings = [r for r in db.select("listings", {"cause_list_id": cause_list_id})
                if r["status"] in ("planned", "accepted")]
    db.update("listings", {"cause_list_id": cause_list_id, "status": "proposed"}, {"status": "dropped"})
    first_day: Dict[str, str] = {}
    for l in listings:
        first_day[l["case_id"]] = min(first_day.get(l["case_id"], l["day"]), l["day"])
    _longer_statement_timeout(db)
    # one multi-row INSERT for every hearing instead of one statement per listing
    db.insert("hearings", [{"case_id": l["case_id"], "hearing_date": l["day"], "bench_id": l["bench_id"]} for l in listings])
    db.update("listings", {"cause_list_id": cause_list_id, "status": ["planned", "accepted"]}, {"status": "published"})
    plan = draft["plan"] or {}
    if plan.get("calendar"):
        _apply_queue(db, plan, cause_list_id, set(first_day))
    cases = store.get_cases(first_day, db=db)
    for case_id, day in first_day.items():
        case = cases.get(case_id)
        if case:
            # only the date changes: one narrow UPDATE (column + the copy kept in `data`) instead of re-inserting the
            # whole row with every index - the full upsert is what hit "canceling statement due to statement timeout"
            data = {k: v for k, v in case.items() if not k.startswith("_") and k not in ("source", "data_quality", "field_provenance")}
            db.update("cases", {"case_id": case_id}, {"next_hearing_date": day, "data": {**data, "next_hearing_date": day}})
    store.upsert_queue_state([{"case_id": c, "last_listed_on": d} for c, d in first_day.items()], db=db)
    db.update("cause_lists", {"id": cause_list_id}, {"status": "published", "approved_by": actor, "decided_at": _now()})
    store.audit(actor, role, "cause_list_published", f"cause_list:{cause_list_id}", {"listings": len(listings)}, db=db)
    db.commit()
    impact.record("cause_list_published", len(listings))
    return {"cause_list_id": cause_list_id, "status": "published", "hearings_created": len(listings)}


def reject(db, cause_list_id: int, actor: str, role: str, note: str = "") -> Dict:
    _draft(db, cause_list_id)
    db.update("listings", {"cause_list_id": cause_list_id, "status": list(OPEN_LISTING)}, {"status": "dropped"})
    db.update("cause_lists", {"id": cause_list_id}, {"status": "rejected", "approved_by": actor, "decided_at": _now()})
    store.audit(actor, role, "cause_list_rejected", f"cause_list:{cause_list_id}", {"note": note}, db=db)
    db.commit()
    return {"cause_list_id": cause_list_id, "status": "rejected"}


# ----------------------------------------------------------------------------- fast lane and slot decisions
def _to_minutes(clock: str) -> float:
    h, m = (int(x) for x in clock.split(":"))
    t = h * 60 + m - (scheduler.DAY_START[0] * 60 + scheduler.DAY_START[1])
    lunch_start = scheduler.LUNCH[0][0] * 60 + scheduler.LUNCH[0][1] - (scheduler.DAY_START[0] * 60 + scheduler.DAY_START[1])
    lunch_len = (scheduler.LUNCH[1][0] * 60 + scheduler.LUNCH[1][1]) - (scheduler.LUNCH[0][0] * 60 + scheduler.LUNCH[0][1])
    return t - lunch_len if t >= lunch_start + lunch_len else t


def _place_in_list(db, cause_list_id: int, case: Dict, band: str, score: float, status: str,
                   only_day: Optional[str] = None, only_bench: Optional[str] = None) -> Optional[Dict]:
    """First free slot at the end of a bench-day in an existing draft list, no advocate clash. Writes the listing."""
    cl = db.select("cause_lists", {"id": cause_list_id})[0]
    start = date.fromisoformat(cl["start_date"])
    plan_days = (cl["plan"] or {}).get("days") or 5
    cal = calendar_rows(db, start, plan_days)
    closed = {c["day"] for c in cal if c["kind"] in scheduler.CLOSED_KINDS and not c.get("bench_id")}
    leave = {(c["day"], c["bench_id"]) for c in cal if c.get("bench_id")}
    rows = [r for r in db.select("listings", {"cause_list_id": cause_list_id}) if r["status"] in OPEN_LISTING]
    advs = case.get("advocate_ids") or []
    others = store.get_cases([r["case_id"] for r in rows], db=db) if advs else {}  # only needed for advocate clashes; one query
    all_benches = load_benches(db)
    result = {"score": score, "band": band, "case": case, "estimated_minutes": triage.estimated_minutes(case),
              "adjournment_risk": triage.adjournment_risk(case)}
    need = scheduler._expected_minutes(result)
    for d in scheduler.working_days(start, plan_days, sorted(closed)):
        day = d.isoformat()
        if only_day and day != only_day:
            continue
        benches = [b for b in all_benches if scheduler._eligible(b, case.get("case_type", "other"))
                   and (day, b["bench_id"]) not in leave and (not only_bench or b["bench_id"] == only_bench)]
        adv_busy = {}
        for r in rows:
            if r["day"] == day:
                for a in others.get(r["case_id"], {}).get("advocate_ids") or []:
                    adv_busy.setdefault((d, a), []).append((r["bench_id"], _to_minutes(r["slot_start"]), _to_minutes(r["slot_end"])))
        for b in sorted(benches, key=lambda b: ("*" in b["case_types"], b["bench_id"])):
            here = [r for r in rows if r["day"] == day and r["bench_id"] == b["bench_id"]]
            used = sum(r["expected_minutes"] or 0 for r in here)
            busy = [(_to_minutes(r["slot_start"]), _to_minutes(r["slot_start"]) + (r["expected_minutes"] or 0)) for r in here]
            # same first-fit search as the planner: gaps left between earlier slots are usable
            begin, _ = scheduler._first_fit(busy, used, need, max(need, 5), b["minutes_per_day"], b["minutes_per_day"],
                                            d, b["bench_id"], advs, adv_busy)
            if begin is None:
                continue
            end = begin + max(need, 5)
            slot = {"cause_list_id": cause_list_id, "case_id": case["case_id"], "day": day, "bench_id": b["bench_id"],
                    "slot_start": scheduler._clock(begin), "slot_end": scheduler._clock(end),
                    "expected_minutes": int(round(need)), "band": band, "score": score, "status": status}
            slot["id"] = db.insert("listings", [slot], returning="id")
            return slot
    return None


def fast_lane(db, case_id: str, today: Optional[date] = None) -> Optional[Dict]:
    """Critical or release-eligible: propose a slot in the nearest open draft list (a fast-lane draft if none)."""
    today = today or date.today()
    row = db.select("cases", {"case_id": case_id})
    if not row or not (row[0]["band"] == "Critical" or "UNDERTRIAL_RELEASE_ELIGIBLE" in (row[0]["flags"] or [])):
        return None
    existing = [l for l in db.select("listings", {"case_id": case_id}) if l["status"] in OPEN_LISTING and l["day"] >= today.isoformat()]
    if existing:
        return existing[0]
    drafts = [c for c in db.select("cause_lists", {"status": "draft"}, order="start_date") if c["start_date"] >= today.isoformat()]
    case = {**(row[0]["data"] or {}), "case_id": case_id}
    for cl in drafts:
        slot = _place_in_list(db, cl["id"], case, row[0]["band"], row[0]["score"], "proposed")
        if slot:
            db.commit()
            return slot
    start = scheduler.add_working_days(today, 1)
    cid = db.insert("cause_lists", [{"court_id": row[0]["court_id"] or "DEMO-DC", "start_date": start.isoformat(),
                                     "plan": {"fast_lane": True, "days": 5}, "metrics": {},
                                     "explanation": "Fast-lane draft for new Critical / release-eligible cases",
                                     "status": "draft", "created_at": _now()}], returning="id")
    slot = _place_in_list(db, cid, case, row[0]["band"], row[0]["score"], "proposed")
    db.commit()
    return slot


def accept_slot(db, case_id: str, action: str, actor: str, role: str, day: Optional[str] = None,
                bench_id: Optional[str] = None, hold_until: Optional[str] = None,
                cause_list_id: Optional[int] = None) -> Dict:
    """Registrar decision on a proposed / planned slot in a draft list: accept, move (day / bench) or hold.
    `cause_list_id` names the draft on screen; without it the fast-lane proposal (else the earliest draft slot) is used."""
    if action not in ("accept", "move", "hold"):
        raise ValueError("action must be accept, move or hold")
    drafts = {c["id"] for c in db.select("cause_lists", {"status": "draft"})}
    if cause_list_id is not None:
        if int(cause_list_id) not in drafts:
            raise ValueError(f"Cause list {cause_list_id} is not an open draft")
        drafts = {int(cause_list_id)}
    slots = [l for l in db.select("listings", {"case_id": case_id}, order="day")
             if l["status"] in OPEN_LISTING and l["cause_list_id"] in drafts]
    if cause_list_id is None:  # Today's "Accept slot": prefer the fast-lane proposal
        slots.sort(key=lambda l: (l["status"] != "proposed", l["day"]))
    if not slots:
        raise LookupError(f"No open draft slot for case {case_id}")
    slot = slots[0]
    out = {"case_id": case_id, "action": action}
    if action == "accept":
        db.update("listings", {"id": slot["id"]}, {"status": "accepted"})
        out["slot"] = {**slot, "status": "accepted"}
    elif action == "move":
        if not (day or bench_id):
            raise ValueError("move needs a day and/or bench_id")
        case = {**(store.get_case(case_id, db=db) or {}), "case_id": case_id}
        db.update("listings", {"id": slot["id"]}, {"status": "dropped"})
        new = _place_in_list(db, slot["cause_list_id"], case, slot["band"], slot["score"], "accepted",
                             only_day=day, only_bench=bench_id)
        if not new:
            db.rollback()
            raise ValueError("No room on that day / bench without a clash")
        out["slot"] = new
    else:
        until = hold_until or (date.today() + timedelta(days=7)).isoformat()
        db.update("listings", {"id": slot["id"]}, {"status": "dropped"})
        store.upsert_queue_state([{"case_id": case_id, "hold_until": until, "last_deferral_reason": "on hold"}], db=db)
        out["hold_until"] = until
    store.audit(actor, role, f"slot_{action}", f"case:{case_id}", {"listing": slot["id"], "day": day, "bench_id": bench_id,
                                                                   "hold_until": out.get("hold_until")}, db=db)
    db.commit()
    return out


# ----------------------------------------------------------------------------- outcomes
OUTCOMES = ("heard", "adjourned", "disposed", "not_reached")


def record_outcome(db, hearing_id: int, outcome: str, actor: str, role: str, reason: Optional[str] = None,
                   next_date: Optional[str] = None) -> Dict:
    if outcome not in OUTCOMES:
        raise ValueError(f"outcome must be one of {', '.join(OUTCOMES)}")
    rows = db.select("hearings", {"hearing_id": hearing_id})
    if not rows:
        raise LookupError(f"No hearing {hearing_id}")
    h = rows[0]
    reason = (reason or "").strip()[:300] or None
    if next_date in ("", None):
        next_date = None
    else:
        try:
            parsed = date.fromisoformat(str(next_date)[:10])
        except ValueError:
            raise ValueError("next_date must be a date in YYYY-MM-DD form")
        if h["hearing_date"] and parsed.isoformat() <= str(h["hearing_date"])[:10]:
            raise ValueError("The next date must be after the hearing date")
        next_date = parsed.isoformat()
    if outcome == "disposed":
        next_date = None   # a disposed matter has no next date
    previous = h.get("outcome")
    db.update("hearings", {"hearing_id": hearing_id}, {"outcome": outcome, "reason": reason, "next_date": next_date})
    case = store.get_case(h["case_id"], db=db)
    if case:
        meta = {k: case.get(k) for k in ("source", "data_quality", "field_provenance")}
        clean = {k: v for k, v in case.items() if not k.startswith("_") and k not in meta}
        clean["last_hearing_date"] = h["hearing_date"]
        if outcome == "adjourned" and previous != "adjourned":   # correcting a recorded outcome must not count twice
            clean["adjournments"] = int(clean.get("adjournments") or 0) + 1
        elif previous == "adjourned" and outcome != "adjourned":
            clean["adjournments"] = max(0, int(clean.get("adjournments") or 0) - 1)
        if outcome == "disposed":
            clean["status"] = "disposed"
        clean["next_hearing_date"] = next_date
        store.upsert_case(clean, source=meta["source"], data_quality=meta["data_quality"],
                          field_provenance=meta["field_provenance"], db=db)
    db.update("listings", {"case_id": h["case_id"], "day": h["hearing_date"], "status": "published"},
              {"status": {"heard": "heard", "disposed": "heard"}.get(outcome, "adjourned")})
    store.audit(actor, role, "hearing_outcome", f"hearing:{hearing_id}",
                {"case_id": h["case_id"], "outcome": outcome, "previous": previous, "next_date": next_date}, db=db)
    db.commit()
    return {"hearing_id": hearing_id, "case_id": h["case_id"], "outcome": outcome, "next_date": next_date,
            "corrected": previous is not None}


# ----------------------------------------------------------------------------- Today counters
def _pipeline(db, pending: List[Dict], listed_ids) -> Dict:
    """How records move between the staff screens, as counts: Intake -> Docket -> Cause list -> hearing,
    with custody cases also checked by the Undertrial watch."""
    lists = db.query("SELECT id, status, start_date FROM cause_lists ORDER BY id DESC LIMIT 1")
    alerts = db.query("SELECT status FROM alerts")   # status only: the details JSON is not needed for counts
    return {
        "intake_in_progress": db.count("ingest_jobs", {"status": ["queued", "running"]}),
        "docket_pending": len(pending),
        "docket_needs_review": sum(1 for c in pending if c["data_quality"] == "needs_review"),
        "listed_upcoming": len(listed_ids),
        "in_custody": sum(1 for c in pending if c.get("accused_in_custody")),
        "alerts_open": sum(1 for a in alerts if a["status"] in ("pending", "approved", "filed", "heard", "release_ordered")),
        "alerts_waiting_decision": sum(1 for a in alerts if a["status"] == "pending"),
        "latest_cause_list": ({"id": lists[0]["id"], "status": lists[0]["status"], "start_date": lists[0]["start_date"]}
                              if lists else None),
    }


def today_counters(db, today: Optional[date] = None) -> Dict:
    today = today or date.today()
    # the counters need six columns, not each case's full JSON document
    pending = db.query("SELECT case_id, band, score, flags, data_quality, accused_in_custody, source, case_type, stage, "
                       "next_hearing_date FROM cases WHERE status = 'pending'", table="cases")
    states = {r["case_id"]: r for r in db.select("case_queue_state")}
    proposed = [l for l in db.select("listings", {"status": "proposed"}) if l["day"] >= today.isoformat()]
    listed_ids = {l["case_id"] for l in db.select("listings", {"status": list(OPEN_LISTING) + ["published"]})
                  if l["day"] >= today.isoformat()}
    sources = staff_api.case_sources(db) if proposed else {}   # two columns, only when there is something to label
    return {
        "critical_waiting": sum(1 for c in pending if c["band"] == "Critical" and c["case_id"] not in listed_ids),
        "release_eligible": sum(1 for c in pending if "UNDERTRIAL_RELEASE_ELIGIBLE" in (c["flags"] or [])),
        "past_deadline": sum(1 for c in pending if (states.get(c["case_id"]) or {}).get("sla_due_on")
                             and states[c["case_id"]]["sla_due_on"] < today.isoformat()),
        "needs_review": sum(1 for c in pending if c["data_quality"] == "needs_review"),
        # created_at only: selecting * here pulled every document's analysis JSON just to count today's uploads
        "uploaded_today": sum(1 for d in db.query("SELECT created_at FROM documents")
                              if str(d["created_at"] or "")[:10] == today.isoformat()),
        "fast_lane_proposals": [{"case_id": l["case_id"], "day": l["day"], "bench_id": l["bench_id"],
                                 "cause_list_id": l["cause_list_id"],
                                 "slot": f"{l['slot_start']}-{l['slot_end']}", "band": l["band"],
                                 "source": sources.get(l["case_id"])} for l in proposed],
        # pending cases only (a disposed case keeps its old queue row) - same population as Insights and the Docket filter
        "deferred_3_plus": sum(1 for c in pending if ((states.get(c["case_id"]) or {}).get("consecutive_deferrals") or 0)
                               >= config.MUST_LIST_AFTER_DEFERRALS),
        "pipeline": _pipeline(db, pending, listed_ids),
        "data_mix": staff_api.data_mix(pending),   # synthetic demo cases vs cases from real uploads / imports
        # triage at a glance: the band split, and the highest-priority cases that hold no upcoming slot yet
        "by_band": {b: sum(1 for c in pending if c["band"] == b) for b in staff_api.BANDS},
        "top_unlisted": _top_unlisted(pending, states, listed_ids, today),
    }


def _top_unlisted(pending: List[Dict], states: Dict, listed_ids, today: date, n: int = 6) -> List[Dict]:
    """Highest-priority pending cases with no upcoming slot, uploads / imports before synthetic examples at the same
    score, each with its plain-words reasons (staff_api.attention_reasons)."""
    rows = []
    for c in pending:
        if c["case_id"] in listed_ids:
            continue
        st = states.get(c["case_id"]) or {}
        row = {"case_id": c["case_id"], "band": c["band"], "score": c["score"], "flags": c["flags"] or [],
               "source": c["source"], "case_type": c["case_type"], "stage": c["stage"],
               "data_quality": c["data_quality"], "next_hearing_date": c["next_hearing_date"],
               "deferred": st.get("consecutive_deferrals") or 0, "sla_due_on": st.get("sla_due_on"),
               "must_list": bool(st.get("must_list")), "listed_on": None}
        rows.append(row)
    rows.sort(key=lambda r: (-(r["score"] or 0), r["source"] == "synthetic", r["case_id"]))
    real = [r for r in rows if r["source"] != "synthetic"][:n]
    top = (real + [r for r in rows if r["source"] == "synthetic"])[:n] if len(real) < n else real
    top.sort(key=lambda r: (r["source"] == "synthetic", -(r["score"] or 0)))   # uploads / imports always on top
    for r in top:
        r["attention"] = staff_api.attention_reasons(r, today.isoformat())
    return top
