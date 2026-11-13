"""Undertrial Watch - a proactive agent that runs nightly (python -m nyayavedika.jobs run undertrial_scan) or on demand.

    START -> scan -> draft* (Send, one per new candidate) -> save -> review [interrupt: human approves] -> apply -> END

Three in four prisoners in India are undertrials (NCRB Prison Statistics). Sec. 479 BNSS entitles
many to release, yet nobody tracks the threshold date. This agent does: it finds custody cases past
(or within 25% of) the threshold, drafts the release application, and queues it for a legal-aid
lawyer / Undertrial Review Committee member to approve. Nothing is filed without a human decision.

Phase 5 fixes: a dismissal needs a reason and may snooze; a dismissed case does not come back the next
night (only after the snooze date, or when its custody facts change). Custody cases missing a custody date
or sentence are listed as "data needed". Alerts follow a lifecycle a lawyer advances. Every draft carries
a checklist of the Sec. 479 conditions a lawyer must verify. The pure functions below need no LangGraph.
"""
import logging
import operator
from datetime import date, datetime, timezone
from typing import Annotated, Dict, List, Optional, TypedDict

from .. import config, impact, llm, store, triage

logger = logging.getLogger(__name__)
NEAR_THRESHOLD_PERCENT = config.NEAR_THRESHOLD_PERCENT
OPEN = ("pending", "approved", "filed", "heard")
TRANSITIONS = {"pending": {"approved", "dismissed"}, "approved": {"filed", "dismissed"}, "filed": {"heard"},
               "heard": {"released", "denied"}, "released": set(), "denied": set(), "dismissed": set()}
CHECKLIST = [
    "Custody period taken from the custody certificate / remand orders [to be verified]",
    "Offence not punishable with death or imprisonment for life [check the charge, not only the FIR]",
    "Delay in trial not attributable to the accused [to be verified from the order sheet]",
    "Sec. 479(2) exception: no other pending case in which the accused is detained [to be verified]",
    "First-time offender (one-third rule) only if no previous conviction [to be verified]",
]
DATA_SOURCES = {"custody_since": "jail superintendent (custody certificate) or the remand order",
                "max_sentence_years": "registry: confirm the Act and section charged"}


class WatchState(TypedDict, total=False):
    court_id: Optional[str]
    candidates: List[dict]
    data_needed: List[dict]
    drafts: Annotated[List[dict], operator.add]
    alert_ids: List[int]
    decisions: Dict[str, dict]
    summary: dict


DRAFT_SYSTEM = """Draft an application under Section 479 of the Bharatiya Nagarik Suraksha Sanhita, 2023
(earlier Section 436A CrPC) for release of an undertrial prisoner on bond, for a legal-aid lawyer to file.
CRITICAL FORMATTING: formal Indian court language, numbered paragraphs, no markdown. Use ONLY the facts
given; leave [placeholders] for names, FIR number and court. State custody period vs statutory maximum,
that the offence is not punishable with death or life imprisonment, that delay is not attributable to the
accused (or [to be verified]), and pray for release on personal bond with or without sureties."""


def _template(c: dict) -> str:
    ut = c["release_check"]
    notes = "".join(f"\n[LAWYER NOTE: {n}]" for n in ut.get("needs_review") or [])
    return f"""IN THE COURT OF [court name]
{c['case_id']}
State v. [name of accused]

APPLICATION UNDER SECTION 479 OF THE BHARATIYA NAGARIK SURAKSHA SANHITA, 2023 FOR RELEASE ON BOND

1. That the applicant/accused has been in judicial custody since {c.get('custody_since')}, i.e. for {ut['custody_days']} days.
2. That the maximum punishment for the offence alleged ({c.get('act', '[Act]')} s.{c.get('section', '[section]')}) is {c.get('max_sentence_years')} years and the offence is not punishable with death or imprisonment for life.
3. That the applicant has undergone detention exceeding {ut.get('basis') or ('one-third' if c.get('first_time_offender') else 'one-half')} of the maximum period ({ut['threshold_days']} days), and is entitled to release under Section 479 BNSS.
4. That the delay in trial is not attributable to the applicant [to be verified from the order sheet].
5. That no other case is pending against the applicant in which he/she is detained [to be verified].{notes}

PRAYER
It is therefore prayed that this Hon'ble Court may be pleased to release the applicant on personal bond, with or without sureties, and pass such other orders as deemed fit.

[Legal Aid Counsel]                                                    Place: [ ]  Date: [ ]
(Draft for a lawyer's review - legal information, not legal advice. Word copy: GET /api/alerts/<id>/release.docx)
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _custody_facts(case: dict) -> dict:
    return {"custody_since": case.get("custody_since"), "max_sentence_years": case.get("max_sentence_years"),
            "first_time_offender": bool(case.get("first_time_offender"))}


def _suppressed(alerts: List[dict], case: dict, now: str) -> bool:
    """Open alert exists, or a dismissal still applies (snooze not over, custody facts unchanged)."""
    for a in alerts:
        if a["status"] in OPEN:
            return True
        if a["status"] in ("dismissed", "released", "denied"):  # closed: back only after the snooze or new facts
            if a["status"] == "dismissed" and a.get("snooze_until"):
                if a["snooze_until"] > now:
                    return True
            elif (a.get("details") or {}).get("facts") == _custody_facts(case):
                return True
    return False


def create_alert(case: dict, release_check: dict, draft: Optional[str] = None, db=None) -> Optional[int]:
    """Queue a human-review alert. Idempotent: skipped while an open or still-valid dismissed alert exists."""
    with store._session(db) as s:
        alerts = s.select("alerts", {"case_id": case["case_id"], "kind": "undertrial_release"})
        if _suppressed(alerts, case, _now()):
            return None
        c = {**case, "release_check": release_check}
        template = _template(c)
        engine = "template" if not draft or draft == template else "ai"  # the screen labels AI-written drafts
        alert_id = s.insert("alerts", [{
            "case_id": case["case_id"], "kind": "undertrial_release", "status": "pending", "created_at": _now(),
            "details": {"release_check": release_check, **_custody_facts(case), "facts": _custody_facts(case),
                        "checklist": CHECKLIST, "draft_engine": engine},
            "draft": draft or template}], returning="id")
        s.commit()
    impact.record("undertrial_flagged", eligible=release_check.get("eligible"))
    return alert_id


def scan_candidates(db=None, court_id: Optional[str] = None, case_ids: Optional[List[str]] = None,
                    today: Optional[date] = None) -> Dict[str, List[dict]]:
    """Custody cases past / near the threshold (not suppressed), plus custody cases whose data is missing."""
    today = today or date.today()
    now = _now()
    with store._session(db) as s:
        store.ensure_database(s)  # migrated at start-up; re-run only if the schema is gone
        alerts: Dict[str, List[dict]] = {}
        for a in s.select("alerts", {"kind": "undertrial_release"}):
            alerts.setdefault(a["case_id"], []).append(a)
        cases = [c for c in store.pending_cases(court_id, db=s) if c.get("accused_in_custody")
                 and (not case_ids or c["case_id"] in case_ids)]
    out, data_needed = [], []
    for case in cases:
        missing = [f for f in ("custody_since", "max_sentence_years") if case.get(f) in (None, "")]
        if missing:
            data_needed.append({"case_id": case["case_id"], "source": case.get("source"), "missing": missing,
                                "who_can_supply": [DATA_SOURCES[f] for f in missing]})
            continue
        ut = triage.undertrial_release_check(case, today)
        if not ut or _suppressed(alerts.get(case["case_id"], []), case, now):
            continue
        if ut["eligible"] or (ut["percent_of_threshold"] or 0) >= NEAR_THRESHOLD_PERCENT:
            out.append({**case, "release_check": ut})
    out.sort(key=lambda c: (c.get("source") == "synthetic", -c["release_check"]["percent_of_threshold"]))
    data_needed.sort(key=lambda c: c.get("source") == "synthetic")
    return {"candidates": out, "data_needed": data_needed}


def _draft_text(c: dict) -> str:
    facts = (f"Case: {c['case_id']}; offence: {c.get('act')} s.{c.get('section')}; custody since {c.get('custody_since')} "
             f"({c['release_check']['custody_days']} days); statutory maximum {c.get('max_sentence_years')} years; "
             f"first-time offender: {c.get('first_time_offender')}; threshold {c['release_check']['threshold_days']} days "
             f"({c['release_check'].get('basis')}); status {c['release_check'].get('status')}.")
    try:
        return llm.text(DRAFT_SYSTEM, facts, fast=True) if llm.available() else _template(c)
    except Exception as exc:
        logger.warning("draft failed for %s: %s", c["case_id"], exc)
        return _template(c)


def run_scan(db=None, court_id: Optional[str] = None, case_ids: Optional[List[str]] = None,
             today: Optional[date] = None) -> Dict:
    """Scan + draft + queue alerts without the graph (nightly job, rescan when custody fields change)."""
    found = scan_candidates(db, court_id, case_ids, today)
    ids = [aid for c in found["candidates"] if c["release_check"]["eligible"]
           for aid in [create_alert(c, c["release_check"], _draft_text(c), db=db)] if aid]
    return {"new_release_alerts": len(ids), "alert_ids": ids,
            "approaching_threshold": sum(1 for c in found["candidates"] if not c["release_check"]["eligible"]),
            "needs_lawyer_review": sum(1 for c in found["candidates"]
                                       if c["release_check"].get("status") in ("needs_review", "likely_eligible")),
            "data_needed": found["data_needed"]}


# ----------------------------------------------------------------------------- lawyer decisions
def advance_alert(alert_id: int, to_status: str, actor: str = "", role: str = "", note: Optional[str] = None,
                  reason: Optional[str] = None, snooze_until: Optional[str] = None, db=None) -> dict:
    """Move an alert along pending -> approved -> filed -> heard -> released | denied (or dismissed)."""
    with store._session(db) as s:
        rows = s.select("alerts", {"id": int(alert_id)})
        if not rows:
            raise LookupError(f"No alert {alert_id}")
        current = rows[0]["status"]
        if to_status not in TRANSITIONS.get(current, set()):
            raise ValueError(f"An alert that is '{current}' cannot become '{to_status}'")
        if to_status == "dismissed" and not (reason or "").strip():
            raise ValueError("Dismissing needs a reason")
        values = {"status": to_status, "decided_at": _now(), "decision_note": note}
        if to_status == "dismissed":
            values.update(dismiss_reason=reason.strip(), snooze_until=snooze_until)
        if actor:
            values["assigned_to"] = actor
        s.update("alerts", {"id": int(alert_id)}, values)
        if actor:
            store.audit(actor, role, f"alert_{to_status}", f"alert:{alert_id}",
                        {"from": current, "reason": reason, "snooze_until": snooze_until}, db=s)
        s.commit()
    if to_status == "approved":
        impact.record("release_application_approved")
    return {"alert_id": int(alert_id), "status": to_status}


def decide_alerts(decisions: Dict, actor: str = "", role: str = "", db=None) -> int:
    """decisions: {alert_id: {"approve": bool, "note": str, "reason": str, "snooze_until": "YYYY-MM-DD"}}"""
    for aid, d in decisions.items():
        advance_alert(int(aid), "approved" if d.get("approve") else "dismissed", actor, role, note=d.get("note"),
                      reason=d.get("reason") or (d.get("note") if not d.get("approve") else None),
                      snooze_until=d.get("snooze_until"), db=db)
    return len(decisions)


def staff_action(db, alert_id: int, action: str, actor: str, role: str) -> dict:
    """Track non-legal staff follow-up without changing the alert's approval state."""
    if role != "staff":
        raise PermissionError("Only court staff can update these follow-up records")
    events = {
        "mark_record_requested": "undertrial_custody_record_marked_requested",
        "mark_record_received": "undertrial_custody_record_marked_received",
        "request_lawyer_review": "undertrial_lawyer_review_flagged",
    }
    if action not in events:
        raise ValueError(f"action must be one of {', '.join(events)}")

    with store._session(db) as s:
        rows = s.select("alerts", {"id": int(alert_id)})
        if not rows:
            raise LookupError(f"No alert {alert_id}")
        alert = rows[0]
        if alert["kind"] != "undertrial_release":
            raise ValueError("Staff follow-up is available only for Undertrial Watch alerts")
        if alert["status"] not in OPEN:
            raise ValueError(f"Cannot update a {alert['status']} alert")

        details = dict(alert.get("details") or {})
        now = _now()
        if action in ("mark_record_requested", "mark_record_received"):
            status = "requested" if action == "mark_record_requested" else "received"
            if details.get("custody_record_status") == status:
                return {"alert_id": int(alert_id), "status": alert["status"], "details": details}
            details.update(custody_record_status=status, custody_record_updated_at=now,
                           custody_record_updated_by=actor)
        else:
            if details.get("lawyer_review_requested_at"):
                return {"alert_id": int(alert_id), "status": alert["status"], "details": details}
            details.update(lawyer_review_requested_at=now, lawyer_review_requested_by=actor)

        s.update("alerts", {"id": int(alert_id)}, {"details": details})
        store.audit(actor, role, f"undertrial_{action}", f"alert:{alert_id}",
                    {"custody_record_status": details.get("custody_record_status"),
                     "lawyer_review_requested": bool(details.get("lawyer_review_requested_at"))}, db=s)
        s.commit()
        case = store.get_case(alert["case_id"], db=s)
        source = (case or {}).get("source") or "unknown"

    impact.record(events[action], source=source)
    return {"alert_id": int(alert_id), "status": alert["status"], "details": details}


# ----------------------------------------------------------------------------- graph nodes
def scan(state: WatchState) -> dict:
    return scan_candidates(court_id=state.get("court_id"))


def fan_out(state: WatchState):
    from langgraph.types import Send
    eligible = [c for c in state["candidates"] if c["release_check"]["eligible"]]
    return [Send("draft", c) for c in eligible] or "save"


def draft(c: dict) -> dict:
    return {"drafts": [{"case_id": c["case_id"], "draft": _draft_text(c)}]}


def save(state: WatchState) -> dict:
    drafts = {d["case_id"]: d["draft"] for d in state.get("drafts", [])}
    ids = []
    for c in state["candidates"]:
        if c["release_check"]["eligible"]:
            aid = create_alert(c, c["release_check"], drafts.get(c["case_id"]))
            if aid:
                ids.append(aid)
    near = sum(1 for c in state["candidates"] if not c["release_check"]["eligible"])
    return {"alert_ids": ids, "summary": {"new_release_alerts": len(ids), "approaching_threshold": near,
                                          "data_needed": state.get("data_needed", []),
                                          "approaching": [{"case_id": c["case_id"], **c["release_check"]}
                                                          for c in state["candidates"] if not c["release_check"]["eligible"]][:50]}}


def review(state: WatchState) -> dict:
    from langgraph.types import interrupt
    if not state.get("alert_ids"):
        return {"decisions": {}}
    decisions = interrupt({"type": "approve_release_applications", "alert_ids": state["alert_ids"],
                           "summary": state["summary"]})
    return {"decisions": decisions or {}}


def apply(state: WatchState) -> dict:
    n = decide_alerts(state.get("decisions") or {})
    return {"summary": {**state.get("summary", {}), "decisions_applied": n}}


_graph = None


def graph():
    global _graph
    if _graph is None:
        from langgraph.graph import END, START, StateGraph
        from .checkpoint import get_checkpointer
        g = StateGraph(WatchState)
        for name, fn in (("scan", scan), ("draft", draft), ("save", save), ("review", review), ("apply", apply)):
            g.add_node(name, fn)
        g.add_edge(START, "scan")
        g.add_conditional_edges("scan", fan_out, ["draft", "save"])
        g.add_edge("draft", "save")
        g.add_edge("save", "review")
        g.add_edge("review", "apply")
        g.add_edge("apply", END)
        _graph = g.compile(checkpointer=get_checkpointer())
    return _graph
