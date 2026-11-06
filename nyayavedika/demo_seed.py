"""Deterministic synthetic demo data. Every row is labelled
synthetic. Same (size, seed, today) -> identical rows.

    python scripts/seed_demo.py --size 2000 --seed 42

build() is pure (returns rows per table); write() replaces earlier synthetic rows, so re-seeding is safe.
The older 600-case generator (sample_data.generate) is unchanged and still drives the regression numbers.
"""
import random
from datetime import date, datetime, time, timedelta, timezone
from typing import Dict, List, Optional

from . import config, sample_data, scheduler, triage

COURT_ID = config.DEMO_COURT_ID
DISTRICTS = ["Hyderabad", "Rangareddy", "Medchal-Malkajgiri", "Warangal", "Karimnagar"]
STATES = ["Telangana", "Andhra Pradesh", "Karnataka", "Maharashtra", "Tamil Nadu"]
DEFERRAL_REASONS = ["capacity", "advocate_conflict", "no_bench", "data_missing"]
ADJOURN_REASONS = ["advocate sought time", "witness absent", "accused not produced", "paucity of time", "counsel absent"]
LEGAL_AID_CLAUSES = ["12(a)", "12(b)", "12(c)", "12(d)", "12(e)", "12(f)", "12(g)", "12(h)"]
# Offences consistent with statute_ref (act, section, max years or "life").
OFFENCES_FINITE = [("BNS", "303", 3), ("BNS", "318", 7), ("BNS", "305", 7), ("BNS", "117(2)", 7), ("BNS", "309", 14),
                   ("NDPS Act", "20", 20), ("BNS", "115", 1)]
OFFENCES_LIFE = [("BNS", "103", "life"), ("BNS", "64", "life"), ("BNS", "109", "life")]
CRIMINAL = ("criminal_trial", "criminal_appeal", "bail", "habeas_corpus")


def _iso(d: date) -> str:
    return d.isoformat()


def _threshold_days(max_years: float, first_time: bool) -> float:
    return float(max_years) * 365 * (1 / 3 if first_time else 1 / 2)


def _bench_for(ctype: str) -> str:
    return next((b["bench_id"] for b in scheduler.DEFAULT_BENCHES if ctype in b["case_types"]), "CR-5")


def _age_days(case: Dict, today: date) -> int:
    return (today - date.fromisoformat(case["filing_date"])).days


def _set_offence(case: Dict, offence) -> None:
    case["act"], case["section"], case["max_sentence_years"] = offence


def _advocates(rng: random.Random, cases: List[Dict]):
    ids = [f"ADV-{i:02d}" for i in range(1, 41)]
    weights = [1 / (i + 1) ** 0.5 for i in range(len(ids))]  # a few busy advocates, so conflicts are real
    links = []
    for c in cases:
        k = len(c.get("advocate_ids") or [1])
        chosen = []
        while len(chosen) < k:
            a = rng.choices(ids, weights)[0]
            if a not in chosen:
                chosen.append(a)
        c["advocate_ids"] = chosen
        links += [{"case_id": c["case_id"], "advocate_id": a, "role": "lead" if i == 0 else "associate"}
                  for i, a in enumerate(chosen)]
    advocates = [{"advocate_id": a, "name": f"Advocate {a[-2:]} (synthetic)", "source": "synthetic"} for a in ids]
    return advocates, links


def _custody(rng: random.Random, cases: List[Dict], today: date) -> List[str]:
    """~5% in custody; round(1.5%) of all cases near or past the Sec. 479 threshold (30 of 2,000)."""
    for c in cases:
        for k in ("accused_in_custody", "custody_since", "first_time_offender", "max_sentence_years"):
            c.pop(k, None)
        if c["case_type"] in CRIMINAL:
            c["accused_in_custody"] = False
            _set_offence(c, rng.choice(OFFENCES_FINITE + OFFENCES_LIFE))
    n_custody, n_near = round(0.05 * len(cases)), round(0.015 * len(cases))
    pool = [c for c in cases if c["case_type"] in ("criminal_trial", "criminal_appeal")]
    rng.shuffle(pool)
    near_ids = []
    for c in pool:
        if len(near_ids) == n_near:
            break
        window = _age_days(c, today) + 180          # arrest up to ~6 months before filing
        first_time = rng.random() < 0.5
        options = [o for o in OFFENCES_FINITE if _threshold_days(o[2], first_time) * 0.8 <= window]
        if not options:
            continue
        _set_offence(c, rng.choice(options))
        thr = _threshold_days(c["max_sentence_years"], first_time)
        days = int(thr * rng.uniform(0.8, min(1.3, window / thr)))
        c.update(accused_in_custody=True, first_time_offender=first_time, custody_since=_iso(today - timedelta(days=days)))
        near_ids.append(c["case_id"])
    rest = [c for c in cases if c["case_type"] in CRIMINAL and c["case_id"] not in near_ids]
    rest.sort(key=lambda c: (c["case_type"] not in ("bail", "habeas_corpus"), rng.random()))  # liberty matters first
    for c in rest[:max(0, n_custody - len(near_ids))]:
        first_time = rng.random() < 0.5
        cap = _age_days(c, today) + 60
        if isinstance(c["max_sentence_years"], (int, float)):
            cap = min(cap, int(_threshold_days(c["max_sentence_years"], first_time) * 0.7))  # stays below 75%
        days = rng.randint(min(20, max(cap, 1)), max(cap, 1))
        c.update(accused_in_custody=True, first_time_offender=first_time, custody_since=_iso(today - timedelta(days=days)))
    return near_ids


def _needs_review(rng: random.Random, cases: List[Dict], protected: List[str]) -> Dict[str, List[str]]:
    """~8% with a missing custody date or stage -> data_quality = needs_review (never filled by a guess)."""
    n = round(0.08 * len(cases))
    custody = [c for c in cases if c.get("accused_in_custody") and c["case_id"] not in protected]
    others = [c for c in cases if not c.get("accused_in_custody")]
    picked = rng.sample(custody, min(len(custody) // 3, n // 4))
    picked += rng.sample(others, n - len(picked))
    missing = {}
    for c in picked:
        field = "custody_since" if c.get("accused_in_custody") else "stage"
        c.pop(field, None)
        c["data_quality"] = "needs_review"
        c["field_provenance"] = {field: {"source": "synthetic", "status": "missing"}}
        missing[c["case_id"]] = [field]
    return missing


def _hearings(rng: random.Random, cases: List[Dict], today: date) -> List[Dict]:
    """0-15 hearings per case; adjournment rate depends on stage plus noise, so adjournments are derived."""
    rows = []
    for c in cases:
        age = _age_days(c, today)
        n = min(15, int(age / 365 * rng.uniform(0.5, 4)), max(age - 8, 0))
        days = sorted(rng.sample(range(7, age), n)) if n else []
        p_adj = min(max(triage.STAGE_ADJ_RISK.get(c.get("stage") or "evidence", 0.4) + rng.gauss(0, 0.08), 0.05), 0.9)
        filed = date.fromisoformat(c["filing_date"])
        dates = [filed + timedelta(days=d) for d in days]
        adjourned = 0
        for i, d in enumerate(dates):
            r = rng.random()
            outcome = "adjourned" if r < p_adj else "not_reached" if r < p_adj + 0.05 else "heard"
            adjourned += outcome == "adjourned"
            rows.append({"case_id": c["case_id"], "hearing_date": _iso(d), "bench_id": _bench_for(c["case_type"]),
                         "outcome": outcome, "reason": rng.choice(ADJOURN_REASONS) if outcome == "adjourned" else None,
                         "next_date": _iso(dates[i + 1]) if i + 1 < len(dates) else None})
        c["adjournments"] = adjourned
        if dates:
            c["last_hearing_date"] = _iso(dates[-1])
        else:
            c.pop("last_hearing_date", None)
        c["next_hearing_date"] = _iso(today + timedelta(days=rng.randint(1, 45)))
    return rows


def _queue(rng: random.Random, cases: List[Dict], scored: Dict[str, Dict], review: Dict, today: date):
    """150 of 2,000 cases carry 1-4 past deferrals (weekly runs); every case gets a queue-state row."""
    deferred = {c["case_id"]: rng.randint(1, 4) for c in rng.sample(cases, round(0.075 * len(cases)))}
    deferrals, queue = [], []
    for c in cases:
        s, k = scored[c["case_id"]], deferred.get(c["case_id"], 0)
        reasons = [rng.choice(DEFERRAL_REASONS) for _ in range(k)]
        for j, reason in enumerate(reasons):
            run_at = datetime.combine(today - timedelta(days=7 * (k - j)), time(18, 0), tzinfo=timezone.utc)
            deferrals.append({"case_id": c["case_id"], "cause_list_id": None, "run_at": run_at.isoformat(),
                              "reason": reason, "score": s["score"], "band": s["band"]})
        queue.append({"case_id": c["case_id"], "first_eligible_on": c["filing_date"],
                      "times_considered": k + (rng.randint(0, 2) if k else 0), "times_deferred": k,
                      "consecutive_deferrals": k, "last_deferral_reason": reasons[-1] if reasons else None,
                      "sla_due_on": _iso(today + timedelta(days=config.SLA_DAYS.get(s["band"], 30))),
                      "aging_boost": 0, "must_list": False, "needs_review": c["case_id"] in review})
    return deferrals, queue


def _calendar(today: date) -> List[Dict]:
    """8 weeks from this Monday: 3 holidays and one judge-leave day for bench CR-2."""
    monday = today - timedelta(days=today.weekday())
    rows = [{"court_id": COURT_ID, "day": _iso(monday + timedelta(days=d)), "kind": "holiday", "bench_id": None,
             "note": "Court holiday (synthetic)"} for d in (9, 28, 46)]
    rows.append({"court_id": COURT_ID, "day": _iso(monday + timedelta(days=15)), "kind": "judge_leave",
                 "bench_id": "CR-2", "note": "Presiding officer on leave (synthetic)"})
    return rows


def _legal_aid(rng: random.Random, today: date, n: int = 200) -> List[Dict]:
    rows = []
    for _ in range(n):
        created = today - timedelta(days=rng.randint(0, 56))
        eligible = rng.random() < 0.7
        status = rng.choices(["checked", "drafted", "applied", "lawyer_assigned"], [30, 30, 25, 15])[0] if eligible else "checked"
        applied = created + timedelta(days=rng.randint(1, 7)) if status in ("applied", "lawyer_assigned") else None
        assigned = applied + timedelta(days=rng.randint(3, 21)) if status == "lawyer_assigned" else None
        rows.append({"created_at": datetime.combine(created, time(11, 0), tzinfo=timezone.utc).isoformat(),
                     "channel": rng.choice(["web", "helpdesk", "paralegal", "jail"]), "district": rng.choice(DISTRICTS),
                     "language": rng.choices(["English", "Hindi", "Telugu"], [3, 2, 5])[0], "state": config.DEMO_STATE,
                     "eligible": eligible, "grounds": sorted(rng.sample(LEGAL_AID_CLAUSES, rng.randint(1, 2))) if eligible else [],
                     "status": status, "applied_on": applied and min(applied, today),
                     "lawyer_assigned_on": assigned and min(assigned, today), "source": "synthetic"})
    return rows


def build(size: int = 2000, seed: int = 42, today: Optional[date] = None) -> Dict[str, List[Dict]]:
    today = today or date.today()
    rng = random.Random(seed * 7919 + 1)   # separate stream from sample_data's own
    cases = sample_data.generate(size, seed=seed, today=today)
    for c in cases:
        c.update(court_id=COURT_ID, source="synthetic")
    advocates, links = _advocates(rng, cases)
    near = _custody(rng, cases, today)
    review = _needs_review(rng, cases, near)
    hearings = _hearings(rng, cases, today)
    scored = {c["case_id"]: triage.score_case(c, today) for c in cases}
    deferrals, queue = _queue(rng, cases, scored, review, today)
    return {
        "courts": [{"court_id": COURT_ID, "name": "District and Sessions Court (demo)", "state": config.DEMO_STATE,
                    "district": DISTRICTS[0], "level": "district"}],
        "benches": [{**{k: b[k] for k in ("bench_id", "name", "case_types", "minutes_per_day")}, "court_id": COURT_ID,
                     "active": True} for b in scheduler.DEFAULT_BENCHES],
        "court_calendar": _calendar(today),
        "cases": cases, "scores": scored, "near_threshold": near, "needs_review": review,
        "advocates": advocates, "case_advocates": links, "hearings": hearings,
        "deferrals": deferrals, "case_queue_state": queue,
        "legal_aid_requests": _legal_aid(rng, today),
        "dlsa_directory": [{"state": config.DEMO_STATE, "district": d, "office": f"District Legal Services Authority, {d}",
                            "address": f"District Court Complex, {d} (synthetic placeholder)", "phone": None,
                            "email": None, "source_url": None, "verified_at": None, "synthetic": True} for d in DISTRICTS],
        "state_legal_aid_params": [{"state": s, "income_limit": config.LEGAL_AID_INCOME_LIMIT, "helpline": "15100",
                                    "source_url": None, "verified_at": None, "synthetic": True} for s in STATES],
    }


SYNTHETIC_CASE_CHILDREN = ("hearings", "case_advocates", "triage_scores", "case_queue_state", "deferrals")


def write(db, data: Dict[str, List[Dict]]) -> Dict[str, int]:
    """Replace earlier synthetic rows with `data`. Uploaded / imported rows are never touched."""
    from . import store
    for table in SYNTHETIC_CASE_CHILDREN:
        db.execute(f"DELETE FROM {table} WHERE case_id IN (SELECT case_id FROM cases WHERE source = 'synthetic')")
    db.delete("cases", {"source": "synthetic"})
    db.delete("legal_aid_requests", {"source": "synthetic"})
    db.delete("advocates", {"source": "synthetic"})
    db.delete("dlsa_directory", {"synthetic": True})
    db.delete("state_legal_aid_params", {"synthetic": True})
    db.delete("court_calendar", {"court_id": COURT_ID})
    db.upsert("courts", data["courts"], ["court_id"])
    db.upsert("benches", data["benches"], ["bench_id"])
    store.upsert_cases(data["cases"], data["scores"], source="synthetic", db=db)
    store.insert_triage_scores(data["scores"].values(), triage.RULES_VERSION, db=db)
    for table in ("court_calendar", "advocates", "case_advocates", "hearings", "deferrals", "case_queue_state",
                  "legal_aid_requests", "dlsa_directory", "state_legal_aid_params"):
        db.insert(table, data[table])
    db.commit()
    return {t: db.count(t) for t in ("cases", "hearings", "advocates", "case_advocates", "deferrals", "case_queue_state",
                                     "triage_scores", "court_calendar", "legal_aid_requests", "dlsa_directory",
                                     "state_legal_aid_params")}
