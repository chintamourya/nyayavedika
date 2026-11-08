"""Cause-list optimisation: assigns triaged cases to bench-days and time slots.

Ideas:
  * Priority first: higher triage score is listed earlier.
  * Realistic sizing: each case consumes its *expected* time (est. minutes weighted by its
    adjournment risk), so lists are full but not impossibly overloaded.
  * No advocate double-booking across courtrooms at overlapping times.
  * Batching: matters under the same Act/Section are heard back-to-back on a bench-day.
Compared against a naive FIFO list (oldest first, nominal minutes) for the impact metrics.

build_cause_list() is the stateless planner (preview / regression). plan_week() extends it with memory
: queue state -> aging boost and must-list, reserved capacity, court calendar, first-fit slots
on every compatible bench then the general bench, backfill with short matters, reasons for every case left
out, and check_plan() invariants. Same input -> same plan.
"""
import math
from datetime import date, datetime, timedelta
from typing import Dict, Iterable, List, Optional, Set

from . import config

DEFAULT_BENCHES = [
    {"bench_id": "CR-1", "name": "Court Room 1 - Sessions", "case_types": ["bail", "criminal_trial", "criminal_appeal", "habeas_corpus"], "minutes_per_day": 300},
    {"bench_id": "CR-2", "name": "Court Room 2 - Magistrate", "case_types": ["cheque_bounce", "criminal_trial", "bail", "domestic_violence", "maintenance"], "minutes_per_day": 300},
    {"bench_id": "CR-3", "name": "Court Room 3 - Civil", "case_types": ["civil_suit", "rent_eviction", "land_revenue", "commercial", "execution", "consumer"], "minutes_per_day": 300},
    {"bench_id": "CR-4", "name": "Court Room 4 - Family & MACT", "case_types": ["matrimonial", "child_custody", "maintenance", "domestic_violence", "motor_accident"], "minutes_per_day": 300},
    {"bench_id": "CR-5", "name": "Court Room 5 - Writs & Service", "case_types": ["*"], "minutes_per_day": 300},
]

DAY_START = config.DAY_START
LUNCH = config.LUNCH
ADJOURNED_MINUTES = config.ADJOURNED_MINUTES
CONFLICT_BUFFER = config.CONFLICT_BUFFER_MINUTES
BAND_RANK = {"Critical": 0, "High": 1, "Medium": 2, "Routine": 3}


def working_days(start: date, count: int, holidays: Optional[List[str]] = None) -> List[date]:
    hol = {datetime.strptime(h, "%Y-%m-%d").date() for h in (holidays or [])}
    days, d = [], start
    while len(days) < count:
        if d.weekday() < 5 and d not in hol:
            days.append(d)
        d += timedelta(days=1)
    return days


def _clock(minute_offset: float) -> str:
    """Convert minutes-since-day-start into a wall-clock string, skipping lunch."""
    start = DAY_START[0] * 60 + DAY_START[1]
    lunch_start = LUNCH[0][0] * 60 + LUNCH[0][1]
    lunch_len = (LUNCH[1][0] * 60 + LUNCH[1][1]) - lunch_start
    t = start + minute_offset
    if t >= lunch_start:
        t += lunch_len
    t = int(round(t))
    return f"{t // 60:02d}:{t % 60:02d}"


def _expected_minutes(r: Dict) -> float:
    p = r["adjournment_risk"]
    return r["estimated_minutes"] * (1 - p) + ADJOURNED_MINUTES * p


def _eligible(bench: Dict, ctype: str) -> bool:
    return "*" in bench["case_types"] or ctype in bench["case_types"]


def _batch_key(case: Dict) -> str:
    act, sec = case.get("act"), case.get("section")
    return f"{act} s.{sec}" if act and sec else ""


def build_cause_list(triaged: List[Dict], start: date, days: int = 5,
                     benches: Optional[List[Dict]] = None, holidays: Optional[List[str]] = None) -> Dict:
    benches = benches or DEFAULT_BENCHES
    day_list = working_days(start, days, holidays)

    # Priority band first, then batch group (so same-issue matters sit together), then score.
    ordered = sorted(triaged, key=lambda r: (BAND_RANK.get(r["band"], 9), _batch_key(r["case"]) or "~", -r["score"]))

    cursor = {(d, b["bench_id"]): 0.0 for d in day_list for b in benches}
    adv_busy: Dict = {}  # (day, advocate) -> list of (bench, start, end)
    listings: Dict = {(d, b["bench_id"]): [] for d in day_list for b in benches}
    unscheduled = []

    for r in ordered:
        case = r["case"]
        need = _expected_minutes(r)
        slot_len = max(need, 5)
        placed = False
        for d in day_list:
            # Prefer the least-loaded eligible bench that day
            candidates = sorted((b for b in benches if _eligible(b, case.get("case_type", "other"))),
                                key=lambda b: ("*" in b["case_types"], cursor[(d, b["bench_id"])]))
            for b in candidates:
                key = (d, b["bench_id"])
                begin = cursor[key]
                if begin + need > b["minutes_per_day"]:
                    continue
                end = begin + slot_len
                if _advocate_conflict(adv_busy, d, b["bench_id"], case.get("advocate_ids", []), begin, end):
                    continue
                cursor[key] = begin + need
                for adv in case.get("advocate_ids", []):
                    adv_busy.setdefault((d, adv), []).append((b["bench_id"], begin, end))
                listings[key].append({
                    "slot": f"{_clock(begin)}-{_clock(end)}",
                    "case_id": case.get("case_id"),
                    "case_type": case.get("case_type"),
                    "stage": case.get("stage"),
                    "band": r["band"],
                    "score": r["score"],
                    "batch": _batch_key(case),
                    "adjournment_risk": r["adjournment_risk"],
                    "advocates": case.get("advocate_ids", []),
                    "route": r["recommended_route"],
                })
                placed = True
                break
            if placed:
                break
        if not placed:
            unscheduled.append({"case_id": case.get("case_id"), "band": r["band"], "score": r["score"]})

    calendar = []
    for d in day_list:
        day_entry = {"date": d.isoformat(), "benches": []}
        for b in benches:
            items = listings[(d, b["bench_id"])]
            day_entry["benches"].append({
                "bench_id": b["bench_id"], "name": b["name"], "cases": items,
                "expected_minutes": round(cursor[(d, b["bench_id"])]),
                "utilisation_percent": round(100 * cursor[(d, b["bench_id"])] / b["minutes_per_day"], 1),
            })
        calendar.append(day_entry)

    metrics = _metrics(triaged, calendar, unscheduled, day_list, benches)
    return {"calendar": calendar, "unscheduled": unscheduled, "metrics": metrics}


def _advocate_conflict(adv_busy, d, bench_id, advocates, begin, end) -> bool:
    for adv in advocates:
        for other_bench, s, e in adv_busy.get((d, adv), []):
            if other_bench != bench_id and begin < e + CONFLICT_BUFFER and s < end + CONFLICT_BUFFER:
                return True
    return False


def _fifo_baseline(triaged: List[Dict], day_list: List[date], benches: List[Dict]) -> Dict:
    """What a typical oldest-first list looks like: nominal minutes, no conflict checks."""
    ordered = sorted(triaged, key=lambda r: r["case"].get("filing_date", ""))
    cursor = {(d, b["bench_id"]): 0.0 for d in day_list for b in benches}
    adv_slots: Dict = {}
    listed, critical_days, conflicts = [], [], 0
    for r in ordered:
        case = r["case"]
        for i, d in enumerate(day_list):
            b = next((b for b in benches if _eligible(b, case.get("case_type", "other"))
                      and cursor[(d, b["bench_id"])] + r["estimated_minutes"] <= b["minutes_per_day"]), None)
            if b:
                begin = cursor[(d, b["bench_id"])]
                end = begin + r["estimated_minutes"]
                for adv in case.get("advocate_ids", []):
                    for ob, s, e in adv_slots.get((d, adv), []):
                        if ob != b["bench_id"] and begin < e and s < end:
                            conflicts += 1
                    adv_slots.setdefault((d, adv), []).append((b["bench_id"], begin, end))
                cursor[(d, b["bench_id"])] = end
                listed.append(r)
                if r["band"] == "Critical":
                    critical_days.append(i)
                break
    return {"listed": listed, "critical_days": critical_days, "advocate_conflicts": conflicts}


def _metrics(triaged, calendar, unscheduled, day_list, benches) -> Dict:
    listed = [c for day in calendar for b in day["benches"] for c in b["cases"]]
    crit_total = sum(1 for r in triaged if r["band"] == "Critical")
    crit_days = [i for i, day in enumerate(calendar) for b in day["benches"] for c in b["cases"] if c["band"] == "Critical"]
    base = _fifo_baseline(triaged, day_list, benches)
    expected_hearings = sum(1 - c["adjournment_risk"] for c in listed)
    base_expected = sum(1 - r["adjournment_risk"] for r in base["listed"])
    util = [b["utilisation_percent"] for d in calendar for b in d["benches"]]
    return {
        "cases_listed": len(listed),
        "cases_carried_over": len(unscheduled),
        "critical_total": crit_total,
        "critical_listed": len(crit_days),
        "critical_avg_wait_days": round(sum(crit_days) / len(crit_days), 2) if crit_days else None,
        "expected_effective_hearings": round(expected_hearings, 1),
        "advocate_conflicts": 0,
        "avg_bench_utilisation_percent": round(sum(util) / len(util), 1) if util else 0,
        "baseline_fifo": {
            "cases_listed": len(base["listed"]),
            "critical_listed": len(base["critical_days"]),
            "critical_avg_wait_days": round(sum(base["critical_days"]) / len(base["critical_days"]), 2) if base["critical_days"] else None,
            "expected_effective_hearings": round(base_expected, 1),
            "advocate_conflicts": base["advocate_conflicts"],
        },
    }


# ============================================================================= memory-aware planner (Phase 5)
AGING_PER_DEFERRAL = config.AGING_PER_DEFERRAL   # aging boost per consecutive deferral (cap: config.AGING_CAP)
AGING_PER_WEEK_LATE = config.AGING_PER_WEEK_LATE  # aging boost per full week past the listing deadline (SLA)
CLOSED_KINDS = ("holiday", "vacation", "lok_adalat")  # no regular list that day (court-wide when bench_id is empty)
# Week balancing: these bands go to the least-loaded day *within their listing deadline* (config.SLA_DAYS, working
# days; ties: the earlier day) instead of the first day with room, so a week with spare bench time is not front-loaded
# onto Monday while Tue-Fri sit idle. Must-list, Critical and release-eligible cases keep the earliest free slot.
# If nothing fits before the deadline, later days are tried earliest-first (better than carrying the case over).
BALANCE_BANDS = ("High", "Medium", "Routine")


def add_working_days(start: date, n: int, closed: Iterable[str] = ()) -> date:
    """The n-th working day after `start` (n = 0 -> start itself if it is a working day)."""
    closed, d, left = set(closed), start, n
    while d.weekday() >= 5 or d.isoformat() in closed:
        d += timedelta(days=1)
    while left > 0:
        d += timedelta(days=1)
        if d.weekday() < 5 and d.isoformat() not in closed:
            left -= 1
    return d


def effective_priority(score: float, band: str, state: Dict, on: date, aging: bool = True) -> Dict:
    """score_eff = min(100, score + min(AGING_CAP, AGING_PER_DEFERRAL*consecutive_deferrals + AGING_PER_WEEK_LATE*weeks_past_SLA));
    must-list rule."""
    consecutive = int(state.get("consecutive_deferrals") or 0)
    sla = state.get("sla_due_on")
    sla_d = date.fromisoformat(sla) if sla else None
    weeks_past = max(0, (on - sla_d).days) // 7 if sla_d else 0
    past = bool(sla_d and on > sla_d)
    boost = min(config.AGING_CAP, AGING_PER_DEFERRAL * consecutive + AGING_PER_WEEK_LATE * weeks_past) if aging else 0
    must = aging and (consecutive >= config.MUST_LIST_AFTER_DEFERRALS or past)
    return {"score_eff": round(min(100.0, score + boost), 1), "aging_boost": boost, "must_list": must,
            "sla_due_on": sla, "days_overdue": max(0, (on - sla_d).days) if sla_d else 0, "past_deadline": past}


def _first_fit(busy: List[tuple], used: float, need: float, slot_len: float, limit: float, capacity: float,
               d, bench_id: str, advocates: List[str], adv_busy: Dict):
    """Earliest start in this bench-day with no overlap, within minutes and with no advocate clash.
    Returns (start, 'ok') or (None, 'capacity' | 'advocate_conflict')."""
    if used + need > limit:
        return None, "capacity"
    # slots start on whole minutes (as a printed list does), so stored times never look closer than they are
    starts = {0.0} | {float(math.ceil(e)) for _, e in busy} | \
        {float(math.ceil(e + CONFLICT_BUFFER)) for a in advocates for _, _, e in adv_busy.get((d, a), [])}
    clash = False
    for s in sorted(starts):
        if s + need > capacity:
            break
        if any(s < e and bs < s + need for bs, e in busy):
            continue
        if _advocate_conflict(adv_busy, d, bench_id, advocates, s, s + slot_len):
            clash = True
            continue
        return s, "ok"
    return None, "advocate_conflict" if clash else "capacity"


def plan_week(triaged: List[Dict], start: date, days: int = 5, benches: Optional[List[Dict]] = None,
              state: Optional[Dict[str, Dict]] = None, calendar: Optional[List[Dict]] = None,
              aging: bool = True, reserve: Optional[float] = None, rules_version: str = "",
              already_listed: Optional[Dict[str, Dict]] = None, balance: bool = True) -> Dict:
    """Plan the week. With balance=True both plans are built and the balanced week is used only when it costs
    nothing: at least as many cases listed, no fewer must-list cases fitted, and no extra deadline alerts. Otherwise
    the packed (earliest-slot) plan is used and metrics.balance_note says why. Same input -> same plan."""
    args = (triaged, start, days, benches, state, calendar, aging, reserve, rules_version, already_listed)
    packed = _plan_week(*args, balance=False)
    if not balance:
        packed["metrics"]["balance_note"] = "Earliest free slot for every case (balancing switched off)."
        return packed
    level = _plan_week(*args, balance=True)
    pm, lm = packed["metrics"], level["metrics"]
    costs = [what for what, worse in (
        ("fewer cases listed", lm["cases_listed"] < pm["cases_listed"]),
        ("fewer must-list cases fitted", lm["must_list_listed"] < pm["must_list_listed"]),
        ("more deadline alerts", lm["deadline_alerts"] > pm["deadline_alerts"]),
        ("rule violations", len(level["violations"]) > len(packed["violations"]))) if worse]
    if costs:
        pm["balanced"] = False
        pm["balance_note"] = ("Packed into the earliest free slots: spreading this week would have meant "
                              + ", ".join(costs) + ".")
        return packed
    lm["balance_note"] = ("Spread across the week: High, Medium and Routine cases go to the least-busy day within their "
                          "listing deadline; Critical, must-list and release-eligible cases keep the earliest slot. "
                          "Same cases listed as packing would.")
    return level


def _plan_week(triaged: List[Dict], start: date, days: int = 5, benches: Optional[List[Dict]] = None,
               state: Optional[Dict[str, Dict]] = None, calendar: Optional[List[Dict]] = None,
               aging: bool = True, reserve: Optional[float] = None, rules_version: str = "",
               already_listed: Optional[Dict[str, Dict]] = None, balance: bool = True) -> Dict:
    """triaged: triage results (with "case"); state: case_queue_state rows by case_id; calendar: court_calendar rows.
    already_listed: case_id -> {day, bench_id, slot, status, cause_list_id} for cases that already hold a firm slot
    (accepted / published / another draft) inside this week; they are not listed again (no duplicate scheduling)."""
    benches = benches or DEFAULT_BENCHES
    state = state or {}
    already_listed = already_listed or {}
    reserve = config.MUST_LIST_RESERVE if reserve is None else reserve
    closed = {c["day"] for c in (calendar or []) if c["kind"] in CLOSED_KINDS and not c.get("bench_id")}
    leave = {(c["day"], c["bench_id"]) for c in (calendar or []) if c.get("bench_id")}
    day_list = working_days(start, days, sorted(closed))
    keys = [(d, b["bench_id"]) for d in day_list for b in benches if (d.isoformat(), b["bench_id"]) not in leave]
    minutes = {b["bench_id"]: b["minutes_per_day"] for b in benches}

    # 1. refresh: only pending cases that are not on hold
    eligible, on_hold, elsewhere = [], [], []
    for r in triaged:
        c, st = r["case"], state.get(r["case_id"], {})
        if (c.get("status") or "pending") not in ("pending", "on_hold"):
            continue
        if r["case_id"] in already_listed:
            elsewhere.append({"case_id": r["case_id"], "band": r["band"], "score": r["score"], **already_listed[r["case_id"]]})
            continue
        hold = st.get("hold_until")
        if c.get("status") == "on_hold" or (hold and hold > start.isoformat()):
            on_hold.append({"case_id": r["case_id"], "hold_until": hold, "reason": "on hold"})
            continue
        pr = effective_priority(r["score"], r["band"], st, start, aging)
        if aging and (r["band"] == "Critical" or "UNDERTRIAL_RELEASE_ELIGIBLE" in r["flags"]):
            pr["must_list"] = True  # 1-day deadline: must-list order is band first, so these always lead
        eligible.append({**r, **pr})

    busy = {k: [] for k in keys}
    used = {k: 0.0 for k in keys}
    must_used = {k: 0.0 for k in keys}
    adv_busy: Dict = {}
    placed: Dict[str, Dict] = {}
    why: Dict[str, str] = {}
    batch_day: Dict[str, date] = {}   # batch key -> the day its first matter landed, so a batch stays together

    def day_load(d) -> float:
        open_keys = [k for k in busy if k[0] == d]
        cap = sum(minutes[b] for _, b in open_keys)
        return sum(used[k] for k in open_keys) / cap if cap else 9.0

    def days_for(r: Dict, phase: str) -> List[date]:
        """Earliest day first, except balanced bands: within the band's deadline the batch's day, then the
        least-loaded day (ties: earliest); then any later day, earliest first."""
        if not (balance and phase != "must" and not r.get("must_list") and r["band"] in BALANCE_BANDS
                and "UNDERTRIAL_RELEASE_ELIGIBLE" not in r["flags"]):
            return day_list
        bk = _batch_key(r["case"])
        window = max(1, int(config.SLA_DAYS.get(r["band"], len(day_list))))   # working days, day_list[0] = day 1
        inside, after = day_list[:window], day_list[window:]
        return sorted(inside, key=lambda d: (not (bk and batch_day.get(bk) == d), round(day_load(d), 2), d)) + after

    def try_place(r: Dict, phase: str) -> bool:
        case = r["case"]
        ctype = case.get("case_type", "other")
        need = _expected_minutes(r)
        slot_len = max(need, 5)
        advs = case.get("advocate_ids", []) or []
        reasons = set()
        for d in days_for(r, phase):
            specific = sorted((b for b in benches if _eligible(b, ctype) and "*" not in b["case_types"]
                               and (d, b["bench_id"]) in busy), key=lambda b: (used[(d, b["bench_id"])], b["bench_id"]))
            general = [b for b in benches if "*" in b["case_types"] and (d, b["bench_id"]) in busy]
            for b in specific + general:  # every compatible bench, then the general bench
                key, cap = (d, b["bench_id"]), minutes[b["bench_id"]]
                reserved_left = max(0.0, reserve * cap - must_used[key])
                limit = cap if phase in ("must", "backfill") else cap - reserved_left
                s, reason = _first_fit(busy[key], used[key], need, slot_len, limit, cap, d, b["bench_id"], advs, adv_busy)
                if s is None:
                    reasons.add(reason)
                    continue
                busy[key].append((s, s + need))
                used[key] += need
                if phase == "must":
                    must_used[key] += need
                for a in advs:
                    adv_busy.setdefault((d, a), []).append((b["bench_id"], s, s + slot_len))
                placed[r["case_id"]] = {"day": d, "bench_id": b["bench_id"], "start": s, "end": s + slot_len,
                                        "need": need, "phase": phase}
                if _batch_key(case):
                    batch_day.setdefault(_batch_key(case), d)
                return True
        why[r["case_id"]] = ("no_bench" if not reasons else "advocate_conflict" if "advocate_conflict" in reasons
                             else "capacity")
        return False

    def tie(r):
        return r["case_id"] or ""  # deterministic order for equal keys

    must = sorted((r for r in eligible if r["must_list"]), key=lambda r: (BAND_RANK.get(r["band"], 9), -r["days_overdue"], tie(r)))
    rest = sorted((r for r in eligible if not r["must_list"]),
                  key=lambda r: (BAND_RANK.get(r["band"], 9), _batch_key(r["case"]) or "~", -r["score_eff"], tie(r)))
    for r in must:
        try_place(r, "must")
    for r in rest:
        try_place(r, "regular")
    left = sorted((r for r in eligible if r["case_id"] not in placed),
                  key=lambda r: (_expected_minutes(r), BAND_RANK.get(r["band"], 9), -r["score_eff"], tie(r)))
    for r in left:  # backfill gaps with short deferred matters
        try_place(r, "backfill")

    by_id = {r["case_id"]: r for r in eligible}
    cal = []
    for d in day_list:
        entry = {"date": d.isoformat(), "benches": []}
        for b in benches:
            key = (d, b["bench_id"])
            items = sorted(((cid, p) for cid, p in placed.items() if (p["day"], p["bench_id"]) == key), key=lambda x: x[1]["start"])
            cases = []
            for cid, p in items:
                r, case = by_id[cid], by_id[cid]["case"]
                cases.append({"slot": f"{_clock(p['start'])}-{_clock(p['end'])}", "start_min": round(p["start"], 1),
                              "end_min": round(p["end"], 1), "expected_minutes": round(p["need"], 1), "case_id": cid,
                              "case_type": case.get("case_type"), "stage": case.get("stage"), "band": r["band"],
                              "score": r["score"], "score_eff": r["score_eff"], "must_list": r["must_list"],
                              "deferred": int((state.get(cid) or {}).get("consecutive_deferrals") or 0),
                              "phase": p["phase"], "batch": _batch_key(case), "adjournment_risk": r["adjournment_risk"],
                              "advocates": case.get("advocate_ids", []) or [], "route": r["recommended_route"]})
            open_day = key in busy
            entry["benches"].append({"bench_id": b["bench_id"], "name": b["name"], "cases": cases, "open": open_day,
                                     "minutes_per_day": b["minutes_per_day"] if open_day else 0,
                                     "expected_minutes": round(used.get(key, 0.0)),
                                     "utilisation_percent": round(100 * used.get(key, 0.0) / b["minutes_per_day"], 1) if open_day else 0.0})
        cal.append(entry)

    unscheduled = [{"case_id": r["case_id"], "band": r["band"], "score": r["score"], "score_eff": r["score_eff"],
                    "must_list": r["must_list"], "reason": why.get(r["case_id"], "capacity")}
                   for r in eligible if r["case_id"] not in placed]
    must_minutes = sum(_expected_minutes(r) for r in must)
    reserve_minutes = sum(reserve * minutes[b] for _, b in keys)
    unplaced_must = [u["case_id"] for u in unscheduled if u["must_list"]]
    shortfall = None
    if must_minutes > reserve_minutes or unplaced_must:
        shortfall = {"must_list_minutes": round(must_minutes), "reserved_minutes": round(reserve_minutes),
                     "must_list_not_listed": unplaced_must,
                     "message": (f"Must-list demand {round(must_minutes)} min exceeds the reserve {round(reserve_minutes)} min"
                                 if must_minutes > reserve_minutes else f"{len(unplaced_must)} must-list case(s) could not be listed")}

    deadline_alerts, watch = [], []
    for r in eligible:
        if r["band"] == "Critical" or "UNDERTRIAL_RELEASE_ELIGIBLE" in r["flags"]:
            due, p = r["sla_due_on"], placed.get(r["case_id"])
            listed_on = p["day"].isoformat() if p else None
            watch.append({"case_id": r["case_id"], "sla_due_on": due, "listed_on": listed_on})
            if not (listed_on and (not due or listed_on <= due)):
                deadline_alerts.append({"case_id": r["case_id"], "band": r["band"], "sla_due_on": due, "listed_on": listed_on,
                                        "message": "Critical / release-eligible case not listed within its deadline"})

    metrics = _metrics(eligible, cal, unscheduled, day_list, benches)
    open_minutes = sum(minutes[b] for _, b in keys)
    metrics.update({
        "avg_bench_utilisation_percent": round(100 * sum(used.values()) / open_minutes, 1) if open_minutes else 0,
        "pending_considered": len(eligible) + len(on_hold) + len(elsewhere), "on_hold": len(on_hold),
        "already_listed": len(elsewhere),
        "must_list_total": len(must), "must_list_listed": len(must) - len(unplaced_must),
        "backfilled": sum(1 for p in placed.values() if p["phase"] == "backfill"),
        "carried_over_by_reason": {k: sum(1 for u in unscheduled if u["reason"] == k) for k in ("capacity", "advocate_conflict", "no_bench")},
        "deadline_alerts": len(deadline_alerts), "aging": aging, "rules_version": rules_version,
        "balanced": balance,
        # share of each day's open bench time that is planned: shows whether the week is front-loaded
        "daily_utilisation_percent": [round(100 * min(day_load(d), 1.0), 1) if day_load(d) < 9 else 0.0 for d in day_list],
    })
    custody_checks = [{"case_id": r["case_id"], "custody_since": r["case"].get("custody_since"), "flags": r["flags"],
                       "needs_review": r.get("needs_review", False)} for r in eligible if r["case"].get("accused_in_custody")]
    plan = {"calendar": cal, "unscheduled": unscheduled, "on_hold": on_hold, "already_listed": elsewhere, "metrics": metrics,
            "capacity_shortfall": shortfall, "deadline_alerts": deadline_alerts, "deadline_watch": watch,
            "custody_checks": custody_checks, "closed_days": sorted(closed),
            "judge_leave": sorted(f"{d} {b}" for d, b in leave), "rules_version": rules_version,
            "start_date": start.isoformat(), "days": days}
    plan["violations"] = check_plan(plan, benches=benches)
    return plan


def check_plan(plan: Dict, pending_ids: Optional[Set[str]] = None, benches: Optional[List[Dict]] = None) -> List[str]:
    """Invariants. Returns human-readable violations; an empty list means the plan is sound."""
    v = []
    listed = [c for d in plan["calendar"] for b in d["benches"] for c in b["cases"]]
    listed_ids = [c["case_id"] for c in listed]
    carried = [u["case_id"] for u in plan["unscheduled"]]
    held = [h["case_id"] for h in plan.get("on_hold", [])]
    elsewhere = [h["case_id"] for h in plan.get("already_listed", [])]
    everything = listed_ids + carried + held + elsewhere
    if len(everything) != len(set(everything)):
        v.append("a case appears twice across listed / carried over / on hold")
    if pending_ids is not None and set(everything) != set(pending_ids):
        missing, extra = set(pending_ids) - set(everything), set(everything) - set(pending_ids)
        v.append(f"nothing lost: {len(missing)} pending case(s) missing, {len(extra)} unknown case(s) in the plan")
    alerted = {a["case_id"] for a in plan.get("deadline_alerts", [])}
    for w in plan.get("deadline_watch", []):
        late = not w["listed_on"] or (w["sla_due_on"] and w["listed_on"] > w["sla_due_on"])
        if late and w["case_id"] not in alerted:
            v.append(f"critical {w['case_id']} not listed by {w['sla_due_on']} and no alert")
    by_day_adv: Dict = {}
    for d in plan["calendar"]:
        for b in d["benches"]:
            cap = b.get("minutes_per_day") or 0
            total = sum(c.get("expected_minutes", 0) for c in b["cases"])
            if b["cases"] and not b.get("open", True):
                v.append(f"{d['date']} {b['bench_id']}: cases listed on a closed bench-day")
            elif b["cases"] and total > cap + 0.5:
                v.append(f"{d['date']} {b['bench_id']}: {total:.0f} min planned > {cap} available")
            for c in b["cases"]:
                for a in c.get("advocates", []):
                    by_day_adv.setdefault((d["date"], a), []).append((b["bench_id"], c.get("start_min", 0), c.get("end_min", 0), c["case_id"]))
    for (day, adv), slots in by_day_adv.items():
        for i, (b1, s1, e1, c1) in enumerate(slots):
            for b2, s2, e2, c2 in slots[i + 1:]:
                if b1 != b2 and s1 < e2 + CONFLICT_BUFFER and s2 < e1 + CONFLICT_BUFFER:
                    v.append(f"{day}: advocate {adv} double-booked ({c1} on {b1}, {c2} on {b2})")
    for c in plan.get("custody_checks", []):
        if not c["custody_since"] and not ("CUSTODY_DATE_MISSING" in c["flags"] and c["needs_review"]):
            v.append(f"custody case {c['case_id']} has no custody date and is not in needs_review")
    return v
