"""Read models for the staff app screens (Phase 8). Thin queries over the store; no new rules.

    docket(filters)        Docket table rows (band / type / flag / deferred 3+ / needs review / custody)
    case_detail(case_id)   Case drawer: brief, priority reasons with points, timeline with source pages,
                           documents, history (hearings + deferrals), provenance and queue state
    alerts(status)         Undertrial cards sorted by days over the legal limit
    weekly()               Insights: longest wait per band, share deferred 3+, past deadline, utilisation, shortfall
    rules()                The scoring, scheduling and Sec. 479 numbers the code uses, for the "How this works" panels
Used by server.py (FastAPI) and scripts/dev_api.py (stdlib demo server) alike.
"""
import re
from datetime import date
from typing import Dict, List, Optional

from . import config, hearing_readiness, store

BANDS = ("Critical", "High", "Medium", "Routine")
DOCKET_COLUMNS = ("case_id, case_type, stage, band, score, flags, data_quality, source, next_hearing_date, "
                  "accused_in_custody")


def docket(db, band: str = "", case_type: str = "", flag: str = "", deferred3: bool = False, needs_review: bool = False,
           custody: bool = False, past_deadline: bool = False, q: str = "", limit: int = 200,
           not_listed: bool = False) -> Dict:
    # band is filtered below, after counting, so by_band shows every band for the other filters (one-click switching)
    where = {"status": "pending", **({"case_type": case_type} if case_type else {})}
    clause, params = db._where("cases", where)
    # only the columns the table shows: SELECT * pulled every case's full JSON document on each filter change
    rows = db.query(f"SELECT {DOCKET_COLUMNS} FROM cases{clause} ORDER BY score DESC", params, table="cases")
    states = {s["case_id"]: s for s in db.select("case_queue_state")}
    today = date.today().isoformat()
    status_order = {"published": 0, "accepted": 1, "planned": 2, "proposed": 3}
    listings = [l for l in db.select("listings", {"status": list(status_order)}) if l["day"] >= today]
    listings.sort(key=lambda l: (l["case_id"], l["day"], status_order[l["status"]], l.get("id") or 0))
    upcoming = {}
    for listing in listings:
        upcoming.setdefault(listing["case_id"], listing)
    out = []
    for r in rows:
        st = states.get(r["case_id"], {})
        if not_listed and r["case_id"] in upcoming:
            continue
        if flag and flag not in (r["flags"] or []):
            continue
        if deferred3 and (st.get("consecutive_deferrals") or 0) < config.MUST_LIST_AFTER_DEFERRALS:
            continue
        if needs_review and r["data_quality"] != "needs_review":
            continue
        if custody and not r["accused_in_custody"]:
            continue
        if past_deadline and not (st.get("sla_due_on") and st["sla_due_on"] < today):
            continue
        if q and q.lower() not in r["case_id"].lower():
            continue
        out.append({"case_id": r["case_id"], "case_type": r["case_type"], "stage": r["stage"], "band": r["band"],
                    "score": r["score"], "flags": r["flags"] or [], "data_quality": r["data_quality"], "source": r["source"],
                    "next_hearing_date": r["next_hearing_date"], "deferred": st.get("consecutive_deferrals") or 0,
                    "sla_due_on": st.get("sla_due_on"), "must_list": bool(st.get("must_list")),
                    "listed_on": (upcoming.get(r["case_id"]) or {}).get("day"),
                    "listing_status": (upcoming.get(r["case_id"]) or {}).get("status")})
    by_band = {b: 0 for b in BANDS}
    for r in out:
        if r["band"] in by_band:
            by_band[r["band"]] += 1
    if band:
        out = [r for r in out if r["band"] == band]
    out.sort(key=lambda r: (r["source"] == "synthetic", -(r["score"] or 0)))
    return {"total": len(out), "rows": out[:limit], "by_band": by_band,
            "types": sorted({r["case_type"] for r in rows if r["case_type"]})}


_POINTS = re.compile(r"([+-]\d+(?:\.\d+)?)\s*$")


def _chips(reasons: List[str]) -> List[Dict]:
    """'Accused in custody +15' -> {text, points} so the UI can show each reason as a chip with its points."""
    return [{"text": _POINTS.sub("", r).strip(), "points": (_POINTS.search(r).group(1) if _POINTS.search(r) else None)}
            for r in reasons or []]


def case_detail(db, case_id: str) -> Optional[Dict]:
    case = store.get_case(case_id, db=db)
    if not case:
        return None
    scores = db.query("SELECT * FROM triage_scores WHERE case_id = :c ORDER BY scored_at DESC", {"c": case_id}, table="triage_scores")
    latest = scores[0] if scores else {}
    docs = db.select("documents", {"case_id": case_id}, order="created_at")
    documents, timeline = [], []
    for d in docs:
        a = d["analysis"] or {}
        inner = a.get("analysis", a)
        documents.append({"doc_id": d["doc_id"], "filename": d["filename"], "doc_type": d["doc_type"], "pages": d["pages"],
                          "label": a.get("label"), "glance": a.get("glance"), "brief": a.get("brief"),
                          "low_confidence_pages": a.get("low_confidence_pages") or []})
        for t in inner.get("timeline", []) or []:
            timeline.append({**t, "doc_id": d["doc_id"], "filename": d["filename"]})
    brief = (case.get("case_brief") or {})
    if brief.get("timeline"):
        names = {d["doc_id"]: d["filename"] for d in docs}
        timeline = [{**t, "filename": names.get(t.get("doc_id"))} for t in brief["timeline"]]
    hearings = db.select("hearings", {"case_id": case_id}, order="hearing_date DESC", limit=30)
    deferrals = db.select("deferrals", {"case_id": case_id}, order="run_at DESC", limit=30)
    alerts = db.select("alerts", {"case_id": case_id}, order="id DESC", limit=20)
    legal_aid_alert = next((alert for alert in alerts
                            if alert["kind"] == "undertrial_release"
                            and (alert.get("details") or {}).get("legal_aid_lawyer_id")), None)
    legal_aid_assignment = None
    if legal_aid_alert:
        details = legal_aid_alert["details"]
        legal_aid_assignment = {
            "lawyer_name": details.get("legal_aid_lawyer_name"),
            "district": details.get("legal_aid_lawyer_district"),
            "alert_status": legal_aid_alert["status"],
            "review_requested_at": details.get("lawyer_review_requested_at"),
        }
    glance = documents[-1]["glance"] if documents and documents[-1]["glance"] else None
    facts = {k: case.get(k) for k in ("case_type", "stage", "filing_date", "accused_in_custody", "custody_since", "act", "section",
                                      "max_sentence_years", "next_hearing_date", "case_number")}
    return {"case_id": case_id, "source": case.get("source"), "data_quality": case.get("data_quality"),
            "review_fields": case.get("review_fields") or [], "facts": facts, "provenance": case.get("field_provenance") or {},
            "glance": glance, "priority": {"score": case.get("_score"), "band": case.get("_band"), "flags": case.get("_flags") or [],
                                           "route": case.get("_route"), "rules_version": latest.get("rules_version"),
                                           "chips": _chips(latest.get("reasons") or []),
                                           "ai_adjustment": latest.get("ai_adjustment"), "ai_reason": latest.get("ai_reason")},
            "timeline": timeline, "documents": documents, "conflicts": brief.get("conflicts") or [],
            "legal_aid_assignment": legal_aid_assignment,
            "readiness": {"items": hearing_readiness.items(case),
                          "signals": hearing_readiness.system_signals(case.get("review_fields") or [],
                                                                       brief.get("conflicts") or [], documents)},
            "history": {"hearings": hearings, "deferrals": deferrals}, "queue": store.queue_state(case_id, db=db) or {},
            "listings": db.select("listings", {"case_id": case_id}, order="day DESC", limit=10)}


def source_page(db, doc_id: str, page: int) -> Optional[Dict]:
    """The exact page a fact came from (cached extracted text), so the drawer can show the brief beside its source."""
    from . import storage
    rows = db.select("documents", {"doc_id": doc_id})
    if not rows:
        return None
    pages = storage.get_pages(doc_id) or []
    hit = next((p for p in pages if p["page"] == int(page)), None)
    return {"doc_id": doc_id, "filename": rows[0]["filename"], "page": int(page), "pages": len(pages),
            "text": hit["text"] if hit else None, "source": hit.get("source") if hit else None}


def case_sources(db) -> Dict[str, str]:
    """case_id -> where the case came from: synthetic (generated demo data) | upload (documents) | csv (import)."""
    return {r["case_id"]: r["source"] for r in db.query("SELECT case_id, source FROM cases", {}, table="cases")}


def data_mix(rows: List[Dict]) -> Dict[str, int]:
    """How many of these cases are synthetic demo data and how many came from real uploads or imports."""
    mix = {"synthetic": 0, "upload": 0, "csv": 0}
    for r in rows:
        key = r.get("source") or "synthetic"
        mix[key] = mix.get(key, 0) + 1
    return mix


def alerts(db, status: str = "pending") -> Dict:
    from . import triage
    rows = db.select("alerts", {"status": status} if status != "all" else None, order="id DESC", limit=200)
    sources = case_sources(db)
    today = date.today()
    live_ids = [a["case_id"] for a in rows if a["status"] in ("pending", "approved", "filed", "heard")]
    cases = store.get_cases(live_ids, db=db)   # one query for every alert, not one SELECT per card
    out = []
    for a in rows:
        rc = (a["details"] or {}).get("release_check") or {}
        if a["status"] in ("pending", "approved", "filed", "heard"):   # still in custody: count to today
            case = cases.get(a["case_id"])
            live = triage.undertrial_release_check(case, today) if case else None
            if live:
                rc = {**rc, **live}
        over = (rc.get("custody_days") or 0) - (rc.get("threshold_days") or 0)
        out.append({**a, "days_over_limit": over, "custody_days": rc.get("custody_days"), "threshold_days": rc.get("threshold_days"),
                    "release_status": rc.get("status"), "basis": rc.get("basis"), "release_notes": rc.get("needs_review") or [],
                    "source": sources.get(a["case_id"]) or ("citizen" if a["kind"] == "release_review_request" else None),
                    "draft_engine": (a["details"] or {}).get("draft_engine") or "template"})
    out.sort(key=lambda a: (a["source"] == "synthetic", -a["days_over_limit"]))
    return {"alerts": out}


def weekly(db) -> Dict:
    today = date.today()
    pending = {r["case_id"]: r for r in db.select("cases", {"status": "pending"})}
    states = [s for s in db.select("case_queue_state") if s["case_id"] in pending]
    longest = {b: 0 for b in BANDS}
    for s in states:
        band = pending[s["case_id"]]["band"]
        if band in longest and s.get("first_eligible_on"):
            longest[band] = max(longest[band], (today - date.fromisoformat(s["first_eligible_on"][:10])).days)
    latest = [c for c in db.select("cause_lists", {"status": ["draft", "published"]}, order="id DESC", limit=20)
              if not (c["plan"] or {}).get("fast_lane")][:1]
    m = (latest[0]["metrics"] or {}) if latest else {}
    plan = (latest[0]["plan"] or {}) if latest else {}
    base = m.get("baseline_fifo") or {}
    return {"longest_wait_days": longest,
            "deferred_3_plus_percent": round(100 * sum(1 for s in states if (s["consecutive_deferrals"] or 0) >= config.MUST_LIST_AFTER_DEFERRALS) / (len(states) or 1), 1),
            "past_deadline": sum(1 for s in states if s.get("sla_due_on") and s["sla_due_on"] < today.isoformat()),
            "utilisation_percent": m.get("avg_bench_utilisation_percent"),
            "capacity_shortfall": bool(plan.get("capacity_shortfall")), "latest_cause_list": latest[0]["id"] if latest else None,
            "latest_cause_list_status": latest[0]["status"] if latest else None,
            # same week, same benches: this plan vs listing oldest-first (the "before" of the before/after)
            "vs_oldest_first": [{"metric": label, "this_plan": m.get(key), "oldest_first": base.get(key), "better": better}
                                for label, key, better in (
                                    ("Average wait of Critical cases (days)", "critical_avg_wait_days", "lower"),
                                    ("Advocate double-bookings", "advocate_conflicts", "lower"),
                                    ("Hearings expected to go ahead", "expected_effective_hearings", "higher"),
                                    ("Cases listed", "cases_listed", "higher")) if key in m] if base else [],
            "data_mix": data_mix(list(pending.values())),
            "note": "Waits count from first_eligible_on (ready to list; the filing date for the seeded backlog)."}


def rules() -> Dict:
    """Read from the same constants the code runs on, so the UI explanations cannot drift from the logic."""
    from . import config, scheduler, triage
    from .agents import undertrial_watch as uw
    P = triage.POINTS
    return {
        "bands": [{"band": b, "min_score": cut, "sla_days": config.SLA_DAYS.get(b)} for b, cut in triage.BAND_CUTS],
        "base_by_type": dict(sorted(triage.TYPE_URGENCY.items(), key=lambda kv: -kv[1])),
        "factors": [
            {"factor": "Case type", "points": "0-30", "rule": "Base urgency by type: liberty and subsistence first (table below)"},
            {"factor": "Waiting time", "points": f"+{P['age_per_year']} per year, max +{P['age_cap']}",
             "rule": "Counted from the day the case became ready to list, else the filing date"},
            {"factor": "Accused in custody", "points": f"+{triage.CUSTODY_POINTS}", "rule": "Anyone held in jail or police custody"},
            {"factor": "Past the Sec. 479 limit", "points": f"+{triage.RELEASE_ELIGIBLE_POINTS}, always Critical",
             "rule": "Custody has crossed one-third (first offence) or one-half of the maximum sentence"},
            {"factor": "Near the Sec. 479 limit", "points": f"+{triage.NEARING_THRESHOLD_POINTS}",
             "rule": f"Custody is at {triage.NEAR_THRESHOLD_PERCENT}% or more of the limit"},
            {"factor": "Time-bound law", "points": "+3",
             "rule": "; ".join(f"{k.replace('_', ' ')}: {v[1]}" for k, v in triage.TIME_BOUND.items())},
            {"factor": "Vulnerable party", "points": f"+{P['vulnerable_each']} each",
             "rule": "Senior citizen, woman or child, person with disability"},
            {"factor": "Chronic adjournment", "points": f"+{P['chronic_adjournment']}",
             "rule": f"{P['chronic_adjournment_at']} or more adjournments - needs a firm listing"},
            {"factor": "Near disposal", "points": f"+{P['near_disposal']}",
             "rule": "Stage is " + ", ".join(s.replace("_", " ") for s in triage.NEAR_DISPOSAL_STAGES)},
            {"factor": "Dormant", "points": f"+{P['dormant']}", "rule": f"Not heard for over {P['dormant_after_days']} days"},
            {"factor": "Legal aid", "points": f"+{P['legal_aid']}", "rule": "A party is represented through legal aid"},
        ],
        "score_cap": 100,
        "rules_version": triage.RULES_VERSION,
        "schedule": {
            "aging_per_deferral": scheduler.AGING_PER_DEFERRAL, "aging_per_week_late": scheduler.AGING_PER_WEEK_LATE,
            "aging_cap": config.AGING_CAP, "must_list_after_deferrals": config.MUST_LIST_AFTER_DEFERRALS,
            "must_list_reserve_percent": round(100 * config.MUST_LIST_RESERVE),
            "lunch": f"{scheduler.LUNCH[0][0]:02d}:{scheduler.LUNCH[0][1]:02d}-{scheduler.LUNCH[1][0]:02d}:{scheduler.LUNCH[1][1]:02d}",
            "day_start": f"{scheduler.DAY_START[0]:02d}:{scheduler.DAY_START[1]:02d}",
            "advocate_buffer_minutes": scheduler.CONFLICT_BUFFER,
            "order": ["Must-list first: Critical / release-eligible cases, cases deferred "
                      f"{config.MUST_LIST_AFTER_DEFERRALS}+ times in a row, and cases past their deadline",
                      "Then everyone else by band, grouped by similar matters, highest effective score first",
                      "Then short matters fill the gaps left in the day (backfill)",
                      "Balancing: when the week has spare time, High, Medium and Routine cases go to the least-busy day "
                      "within their listing deadline instead of piling onto Monday; this is used only if it lists as "
                      "many cases as packing would, otherwise the week is packed into the earliest slots"],
            "effective_score": f"score + min({config.AGING_CAP}, {scheduler.AGING_PER_DEFERRAL} x deferrals in a row + "
                               f"{scheduler.AGING_PER_WEEK_LATE} x weeks past the deadline)",
        },
        "undertrial": {
            "law": "Sec. 479 BNSS (earlier Sec. 436A CrPC)",
            "first_offender": "one-third of the maximum sentence", "others": "one-half of the maximum sentence",
            "unknown_offender": "one-third is used until confirmed, so nobody is missed",
            "excluded": "offences punishable with death or life imprisonment; several pending offences/cases need a lawyer",
            "near_percent": uw.NEAR_THRESHOLD_PERCENT,
            "transitions": {k: sorted(v) for k, v in uw.TRANSITIONS.items()},
            "checklist": uw.CHECKLIST,
        },
        "intake": {"stages": ["queued", "reading", "summarising", "extracting", "scored", "proposed"],
                   "allowed_types": config.ALLOWED_EXTS, "max_files": config.DEMO_MAX_FILES,
                   "max_pages": config.DEMO_MAX_PAGES},
    }
