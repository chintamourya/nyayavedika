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
# The Sec. 479 BNSS path as it runs in an Indian court, and who holds each power:
#   pending          the watch found custody past the one-third / one-half mark (the jail superintendent must also
#                    apply under Sec. 479(3); the Under Trial Review Committee reviews such cases)
#   approved         COUNSEL for the undertrial (usually a DLSA legal-aid lawyer) decides to file the application
#   dismissed        counsel decides not to file, with a reason (e.g. another detaining case; not a first offence)
#   filed            the court REGISTRY records the application as registered (petition number, if any)
#   heard            the court heard it (the Public Prosecutor is heard before any order)
#   release_ordered  the COURT ordered release - on bail (one-half), or on bond (first-time offender, one-third)
#   denied           the COURT ordered continued detention, with reasons recorded in writing
#   released         released from custody after the bail / bond was furnished and accepted
# Only counsel decides whether to file; only the court decides release; court staff record what the court did.
OPEN = ("pending", "approved", "filed", "heard", "release_ordered")   # the person is still in custody
TRANSITIONS = {"pending": {"approved", "dismissed"}, "approved": {"filed", "dismissed"},
               "filed": {"heard", "release_ordered", "denied"},    # an order can come at the first listing
               "heard": {"release_ordered", "denied"}, "release_ordered": {"released"},
               "released": set(), "denied": set(), "dismissed": set()}
COUNSEL_STEPS = ("approved", "dismissed")                                  # counsel's decision
REGISTRY_STEPS = ("filed", "heard", "release_ordered", "denied", "released")   # recorded by court staff
STEP_ROLES = {**{s: ("lawyer",) for s in COUNSEL_STEPS}, **{s: ("staff",) for s in REGISTRY_STEPS}}
NOTE_REQUIRED = {"release_ordered": "Record the court's order: on bail or on bond, and the order date",
                 "denied": "Record the order date and that reasons for continued detention were recorded by the court"}
STEP_LABEL = {"approved": "counsel decided to file", "dismissed": "counsel decided not to file",
              "filed": "application registered", "heard": "heard by the court",
              "release_ordered": "court ordered release", "denied": "court ordered continued detention",
              "released": "released from custody"}
# kept for callers written against the earlier names
LAWYER_DECISIONS = COUNSEL_STEPS
LAWYER_DECIDES_ROLES = ("lawyer",)
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
    # Sec. 479(1): release on bail after one-half; a first-time offender on bond after one-third
    relief = "ON BOND" if c.get("first_time_offender") else "ON BAIL" if c.get("first_time_offender") is False else "ON BAIL / BOND"
    return f"""IN THE COURT OF [court name]
{c['case_id']}
State v. [name of accused]

APPLICATION UNDER SECTION 479 OF THE BHARATIYA NAGARIK SURAKSHA SANHITA, 2023 FOR RELEASE {relief}

1. That the applicant/accused has been in judicial custody since {c.get('custody_since')}, i.e. for {ut['custody_days']} days.
2. That the maximum punishment for the offence alleged ({c.get('act', '[Act]')} s.{c.get('section', '[section]')}) is {c.get('max_sentence_years')} years and the offence is not punishable with death or imprisonment for life.
3. That the applicant has undergone detention exceeding {ut.get('basis') or ('one-third' if c.get('first_time_offender') else 'one-half')} of the maximum period ({ut['threshold_days']} days), and is liable to be released under Section 479 BNSS.
4. That the delay in trial is not attributable to the applicant [to be verified from the order sheet].
5. That no other case is pending against the applicant in which he/she is detained [to be verified].{notes}

PRAYER
It is therefore prayed that this Hon'ble Court may be pleased to release the applicant {"on bond" if c.get("first_time_offender") else "on bail"} under Section 479 BNSS, on personal bond with or without sureties, and pass such other orders as deemed fit.

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
    """Move an alert one step along the Sec. 479 path (see TRANSITIONS above).
    Counsel (lawyer role) decides whether to file; court staff record what the court did. A role may only take its
    own steps; an internal call without a role (the watch graph's resume) is trusted."""
    if role and to_status in STEP_ROLES and role not in STEP_ROLES[to_status]:
        raise PermissionError(
            "Only counsel for the undertrial (the legal-aid lawyer) decides whether to file the application."
            if to_status in COUNSEL_STEPS else
            "Court events - registration, hearing, the court's order and release - are recorded by court staff.")
    if to_status in NOTE_REQUIRED and not (note or "").strip():
        raise ValueError(NOTE_REQUIRED[to_status])
    with store._session(db) as s:
        rows = s.select("alerts", {"id": int(alert_id)})
        if not rows:
            raise LookupError(f"No alert {alert_id}")
        current = rows[0]["status"]
        if to_status not in TRANSITIONS.get(current, set()):
            raise ValueError(f"An alert that is '{current}' cannot become '{to_status}'")
        if to_status == "dismissed" and not (reason or "").strip():
            raise ValueError("Dismissing needs a reason")
        details = dict(rows[0].get("details") or {})
        if role == "lawyer" and to_status in COUNSEL_STEPS and not has_counsel_on_record(rows[0]):
            raise PermissionError("The court registry must record counsel on the alert before counsel can decide.")
        details["steps"] = list(details.get("steps") or []) + [
            {"status": to_status, "at": _now(), "by": actor or "system", "role": role or "system",
             "note": (note or reason or "").strip()[:500] or None}]
        values = {"status": to_status, "decided_at": _now(), "decision_note": note, "details": details}
        if to_status == "dismissed":
            values.update(dismiss_reason=reason.strip(), snooze_until=snooze_until)
        if actor:
            values["assigned_to"] = actor
        s.update("alerts", {"id": int(alert_id)}, values)
        if actor:
            store.audit(actor, role, f"alert_{to_status}", f"alert:{alert_id}",
                        {"from": current, "reason": reason, "note": note, "snooze_until": snooze_until}, db=s)
        s.commit()
    if to_status == "approved":
        impact.record("release_application_approved")
    return {"alert_id": int(alert_id), "status": to_status}


COUNSEL_BASIS = {"dlsa_assignment": "DLSA assignment letter (legal aid)", "vakalatnama": "Vakalatnama filed"}


def has_counsel_on_record(alert: dict) -> bool:
    counsel = ((alert.get("details") or {}).get("counsel") or {})
    return bool(str(counsel.get("name") or "").strip())


def require_counsel_for_decisions(decisions: Dict, role: str, db=None) -> None:
    if role != "lawyer":
        return
    with store._session(db) as s:
        for alert_id in decisions:
            rows = s.select("alerts", {"id": int(alert_id)})
            if not rows:
                raise LookupError(f"No alert {alert_id}")
            if not has_counsel_on_record(rows[0]):
                raise PermissionError("The court registry must record counsel on the alert before counsel can decide.")


def assign_counsel(alert_id: int, name: str, basis: str, reference: str = "", actor: str = "", role: str = "",
                   db=None) -> dict:
    """Court staff record counsel on record for the person, from the DLSA assignment letter or a vakalatnama -
    the documents that link a lawyer to a case in court. NyayaVedika does not appoint anyone. Replaces any earlier
    entry (counsel can change); every change is in the audit log."""
    name = " ".join(str(name or "").split())[:120]
    reference = " ".join(str(reference or "").split())[:120]
    if len(name) < 3:
        raise ValueError("Give counsel's name as on the assignment letter or vakalatnama")
    if basis not in COUNSEL_BASIS:
        raise ValueError(f"basis must be one of: {', '.join(COUNSEL_BASIS)}")
    with store._session(db) as s:
        rows = s.select("alerts", {"id": int(alert_id)})
        if not rows:
            raise LookupError(f"No alert {alert_id}")
        details = dict(rows[0].get("details") or {})
        counsel = {"name": name, "basis": basis, "basis_label": COUNSEL_BASIS[basis], "reference": reference or None,
                   "recorded_at": _now(), "recorded_by": actor or "system"}
        details["counsel"] = counsel
        s.update("alerts", {"id": int(alert_id)}, {"details": details})
        store.audit(actor, role, "alert_counsel_recorded", f"alert:{alert_id}",
                    {"name": name, "basis": basis, "reference": reference or None}, db=s)
        s.commit()
    return {"alert_id": int(alert_id), "counsel": counsel}


def decide_alerts(decisions: Dict, actor: str = "", role: str = "", db=None) -> int:
    """decisions: {alert_id: {"approve": bool, "note": str, "reason": str, "snooze_until": "YYYY-MM-DD"}}"""
    require_counsel_for_decisions(decisions, role, db)
    for aid, d in decisions.items():
        advance_alert(int(aid), "approved" if d.get("approve") else "dismissed", actor, role, note=d.get("note"),
                      reason=d.get("reason") or (d.get("note") if not d.get("approve") else None),
                      snooze_until=d.get("snooze_until"), db=db)
    return len(decisions)


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
