"""One tool registry for Nyaya Mitra. Deterministic legal logic stays in code (auditable);
the LLM decides *which* tool to use and *how to explain* the result.

Each tool has: name, description, argument doc, a function, and five routing fields -
    roles             who may use it (citizen / lawyer / staff); lists are built by filtering on the token's role
    has_side_effects  creates or changes a record -> needs an explicit "yes" in the chat before it runs
    needs_file        works on an attached file
    needs_approval    a person decides afterwards (lawyer, Registrar)
    screen            the UI route that a hand-over opens
Rule: read-only, no file, no change -> used internally; otherwise it is a hand-over. The confirmation gate lives
in Tool.run (confirmed=...) and only the conversation layer can set it - the model cannot.
"""
import hashlib
import json
import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable, Dict, List, Optional, Tuple

from .. import config, drafting, impact, legal_aid, triage, vectorstore, websearch

logger = logging.getLogger(__name__)
CITIZEN, LAWYER, STAFF = "citizen", "lawyer", "staff"
EVERYONE = (CITIZEN, LAWYER, STAFF)
COURT = (LAWYER, STAFF)


@dataclass
class Tool:
    name: str
    description: str
    args: str
    fn: Callable[..., Any]
    roles: Tuple[str, ...] = EVERYONE
    has_side_effects: bool = False
    needs_file: bool = False
    needs_approval: bool = False
    screen: Optional[str] = None
    confirm_question: str = ""
    wants_ctx: bool = False  # receives _ctx={"role", "actor"} from the conversation layer

    @property
    def mode(self) -> str:
        return "hand_over" if (self.has_side_effects or self.needs_approval) else "internal"

    def run(self, ctx: Optional[Dict] = None, confirmed: bool = False, **kwargs) -> Any:
        kwargs = {k: v for k, v in kwargs.items() if k not in ("confirmed", "_ctx", "ctx")}  # never from the model
        role = (ctx or {}).get("role")
        if role and role not in self.roles:
            return {"error": f"{self.name} is not available in this mode"}
        if self.has_side_effects and not confirmed:
            return {"needs_confirmation": True, "tool": self.name, "args": kwargs,
                    "question": self.confirm_question or f"Shall I go ahead with {self.name.replace('_', ' ')}?"}
        try:
            out = self.fn(_ctx=ctx or {}, **kwargs) if self.wants_ctx else self.fn(**kwargs)
        except TypeError as exc:
            return {"error": f"bad arguments for {self.name}: {exc}. Expected: {self.args}"}
        except Exception as exc:
            logger.exception("tool %s failed", self.name)
            return {"error": f"{self.name} failed: {exc}"}
        impact.record("agent_tool", tool=self.name, role=role or "-")  # tool name only, no personal data
        return out


def catalogue(tools: List["Tool"]) -> str:
    lines = []
    for t in tools:
        tag = " [hand-over: ask the person for a clear yes first]" if t.mode == "hand_over" else ""
        tag += " [needs an attached file]" if t.needs_file else ""
        lines.append(f"- {t.name}({t.args}): {t.description}{tag}")
    return "\n".join(lines)


def capabilities(tools: List["Tool"]) -> str:
    """Capability summary for the system prompt, generated from the registry (a new tool needs no prompt edit)."""
    internal = [t.name for t in tools if t.mode == "internal"]
    hand = [t.name for t in tools if t.mode == "hand_over"]
    return (f"You can do these yourself: {', '.join(internal)}.\n"
            + (f"These hand work to a person or another screen and need the user's explicit yes first: {', '.join(hand)}.\n"
               if hand else ""))


def observation_text(obs: Any, limit: int = 3500) -> str:
    s = obs if isinstance(obs, str) else json.dumps(obs, default=str, ensure_ascii=False)
    return s if len(s) <= limit else s[:limit] + " …[truncated]"


def _session():
    from .. import store
    return store.connect()


# ----------------------------------------------------------------------------- legal aid (everyone, internal)
def _applicant(args: Dict) -> Dict:
    return {k: v for k, v in args.items() if k not in ("language", "channel", "problem")}


def _check_legal_aid(district: str = "", language: str = "English", channel: str = "web", **applicant) -> Dict:
    result = legal_aid.check_eligibility({**applicant, **({"district": district} if district else {})})
    impact.record("legal_aid_check", eligible=result["eligible"], outcome=result["outcome"], channel="assistant")
    try:
        with _session() as s:  # categories, district and outcome only
            s.insert("legal_aid_requests", [{"channel": channel, "district": district or None, "state": result["state"],
                                             "language": language, "eligible": result["eligible"],
                                             "grounds": [g["clause"] for g in result["grounds"]], "status": "checked",
                                             "source": "assistant"}])
    except Exception as exc:
        logger.warning("legal aid request not stored: %s", exc)
    return result


def _draft_legal_aid_application(problem: str = "", language: str = "English", **applicant) -> Dict:
    elig = legal_aid.check_eligibility(applicant)
    out = legal_aid.draft_application(applicant, elig, problem, language)
    impact.record("legal_aid_application", engine=out["engine"])
    out["actions"] = [{"label": "Download application (Word)", "route": "/api/legal-aid/application.docx", "method": "POST",
                       "prefill": {"applicant": _applicant(applicant), "problem": problem,
                                   "district": applicant.get("district", ""), "state": applicant.get("state", "")}}]
    return out


def _find_legal_aid_office(district: str = "", state: str = "") -> Dict:
    state = state or config.DEMO_STATE
    office = legal_aid.where_to_go(state, district or None)
    out = {"office": office, "helpline": legal_aid.HELPLINE}
    if not office.get("district") and websearch.available():  # dated web fallback, trusted domains only
        res = websearch.search(f"District Legal Services Authority {district} {state} address phone", max_results=3)
        out["web"] = [{"title": r.get("title"), "url": r.get("url"), "checked_on": date.today().isoformat()}
                      for r in res.get("results", [])]
    return out


def _legal_aid_kb_search(query: str, top_k: int = 4) -> Dict:
    from .. import legal_aid_kb
    return legal_aid_kb.search(query, top_k)


def _state_legal_aid_fact(state: str, key: str = "income_limit") -> Dict:
    return legal_aid.get_state_fact(state, key)


def _search_law(query: str, top_k: int = 5) -> Dict:
    if not vectorstore.available():
        return {"error": "knowledge base unavailable", "hint": "use legal_aid_kb_search or web_search for official sources"}
    hits = vectorstore.search(config.NS_LAW, query, top_k) + vectorstore.search(config.NS_JUDGMENTS, query, max(2, top_k // 2))
    hits.sort(key=lambda h: h["score"], reverse=True)
    return {"passages": [{"source": h.get("source") or h.get("title"), "section": h.get("section"),
                          "url": h.get("url"), "text": h["text"][:900], "score": h["score"]} for h in hits[:top_k]]}


def _web_search(query: str) -> Dict:
    out = websearch.search(query, max_results=5, trusted_only=True)
    out["checked_on"] = date.today().isoformat()  # web facts always carry their date
    return out


# ----------------------------------------------------------------------------- custody / release
def _check_undertrial_release(custody_since: str, max_sentence_years: Any, first_time_offender: bool = False,
                              offence: str = "") -> Dict:
    if triage.charge_is_life_or_death(offence):
        # the charge decides, not the number the person gave: murder etc. carry death / life
        return {"applicable": False, "life_or_death": True,
                "reason": "Not applicable: the charge described (murder or a similar offence) is punishable with death or "
                          "life imprisonment, and Sec. 479 BNSS does not cover those. Regular bail may still be possible - "
                          "a legal-aid lawyer should check the exact section and advise"}
    case = {"accused_in_custody": True, "custody_since": custody_since, "offence": offence,
            "max_sentence_years": max_sentence_years, "first_time_offender": first_time_offender}
    res = triage.undertrial_release_check(case, date.today())
    if res is None:
        return {"applicable": False, "reason": "Not applicable: offence punishable with death/life, or dates missing"}
    return {"applicable": True, **res,
            "law": "Sec. 479 BNSS (earlier Sec. 436A CrPC): release on bond after half the maximum sentence "
                   "(one-third for first-time offenders); the jail superintendent must apply to the court."}


def _request_release_review(custody_since: str, max_sentence_years: Any, first_time_offender: Optional[bool] = None,
                            description: str = "", case_number: str = "", offence: str = "",
                            _ctx: Optional[Dict] = None) -> Dict:
    """Queue a review request for a legal-aid lawyer (who decides). Facts only - no names or numbers."""
    from .undertrial_watch import CHECKLIST, _template
    check = _check_undertrial_release(custody_since, max_sentence_years, bool(first_time_offender),
                                      offence or description)
    if not check.get("applicable"):
        return {"queued": False, "reason": check["reason"]}
    digest = hashlib.sha256(f"{custody_since}|{max_sentence_years}|{description}".encode()).hexdigest()[:6].upper()
    rid = f"REQ/{date.today().year}/{digest}"  # same facts -> same reference, so a repeat does not queue twice
    facts = {"custody_since": custody_since, "max_sentence_years": max_sentence_years,
             "first_time_offender": first_time_offender}
    with _session() as s:
        open_req = [a for a in s.select("alerts", {"case_id": case_number or rid, "kind": "release_review_request"})
                    if a["status"] in ("pending", "approved")]
        if open_req:
            return {"queued": False, "alert_id": open_req[0]["id"], "reason": "A review request is already with a lawyer"}
        aid = s.insert("alerts", [{"case_id": case_number or rid, "kind": "release_review_request", "status": "pending",
                                   "details": {"release_check": {k: check[k] for k in ("custody_days", "threshold_days", "eligible",
                                                                                       "percent_of_threshold", "status", "basis",
                                                                                       "needs_review")},
                                               **facts, "facts": facts, "raised_by": (_ctx or {}).get("role"),
                                               "checklist": CHECKLIST, "summary": description[:300]},
                                   "draft": _template({"case_id": case_number or rid, **facts, "release_check": check})}],
                       returning="id")
    impact.record("release_review_requested", eligible=check["eligible"])
    return {"queued": True, "alert_id": aid, "reference": case_number or rid,
            "next": "A legal-aid lawyer will review the facts and decide on filing. Keep the jail and case details ready."}


def _get_undertrial_alerts(status: str = "pending", limit: int = 20) -> Dict:
    with _session() as s:
        rows = s.select("alerts", {"status": status}, order="id DESC", limit=limit)
    return {"count": len(rows), "alerts": [{"id": r["id"], "case_id": r["case_id"], "kind": r["kind"], "status": r["status"],
                                            "custody_days": ((r["details"] or {}).get("release_check") or {}).get("custody_days"),
                                            "threshold_days": ((r["details"] or {}).get("release_check") or {}).get("threshold_days")}
                                           for r in rows], "screen": "/lawyer/alerts"}


# ----------------------------------------------------------------------------- documents
def _analyze_document(batch_id: str = "", _ctx: Optional[Dict] = None, wait_seconds: float = 150.0) -> Dict:
    """Runs the intake pipeline on the file(s) attached in this chat and returns the plain summary + deadlines.
    Staff also get the brief, the priority and an Open case card; for citizens nothing enters the docket.
    Files the background worker already holds are waited for (up to wait_seconds); the rest run here."""
    import time
    from .. import intake, worker
    if not batch_id:
        return {"error": "No file is attached to this message. Ask the person to attach it with the paperclip."}
    try:
        status = intake.batch_status(batch_id)
    except intake.IntakeError as exc:
        return {"error": exc.message}
    for f in status["files"]:
        if f["status"] == "queued":
            worker.run_job_now(f["job_id"])
    deadline = time.monotonic() + wait_seconds
    while time.monotonic() < deadline:
        status = intake.batch_status(batch_id)
        if not any(f["status"] == "running" for f in status["files"]):
            break
        time.sleep(config.AGENT_JOB_POLL_SECONDS)
    status = intake.batch_status(batch_id)
    staff = (_ctx or {}).get("role") in COURT
    out, actions = [], []
    for f in status["files"]:
        r = f["result"] or {}
        item = {"file": f["filename"], "status": f["status"], "stage": f["stage"], "error": f["error"]}
        if f["status"] == "done":
            item["error"] = None
            if r.get("case_id") is None:  # citizen: summary only
                item.update(summary=r.get("plain"), glance=r.get("glance"), deadlines=r.get("deadlines"), label=r.get("label"))
            else:
                item.update(brief=r.get("brief"), band=r.get("band"), score=r.get("score"), reasons=r.get("reasons", [])[:5],
                            review_fields=r.get("review_fields"), case_id=r.get("case_id"), label=r.get("label"))
                if staff:
                    actions.append({"label": "Open case", "route": f"/staff/cases/{r['case_id']}", "prefill": {"case_id": r["case_id"]}})
        elif f["status"] in ("queued", "running"):
            item["error"] = "Still being read - ask again in a minute." if f["status"] == "running" else \
                (f["error"] or "Could not be read just now. Please try again.")
        out.append(item)
    for r in status.get("not_queued", []):
        if r["status"] == "skipped":
            continue
        item = {"file": r["filename"], "status": r["status"], "error": r.get("reason")}
        if r["status"] == "duplicate" and r.get("doc_id"):
            if staff:  # the file is already in the docket: show what the system holds instead of reading it again
                with _session() as s:
                    rows = s.select("documents", {"doc_id": r["doc_id"]})
                a = (rows[0]["analysis"] or {}) if rows else {}
                item.update(duplicate_of=r.get("case_id"), brief=a.get("glance"), label=a.get("label"), case_id=r.get("case_id"))
                if r.get("case_id"):
                    actions.append({"label": "Open case", "route": f"/staff/cases/{r['case_id']}", "prefill": {"case_id": r["case_id"]}})
            else:
                item["error"] = "This file was already uploaded."
        out.append(item)
    return {"files": out, "actions": actions}


def _explain_document(doc_id: str) -> Dict:
    with _session() as s:
        rows = s.select("documents", {"doc_id": doc_id})
    if not rows:
        return {"error": "document not found - attach it in the chat"}
    a = rows[0]["analysis"] or {}
    inner = a.get("analysis", a)
    return {"plain": a.get("plain") or inner.get("plain_language_summary"), "glance": a.get("glance"),
            "directions_and_deadlines": inner.get("directions_and_deadlines"), "outcome": inner.get("outcome")}


# ----------------------------------------------------------------------------- docket (staff) and case status (citizen)
def _lookup_case(case_id: str) -> Dict:
    from .. import store
    case = store.get_case(case_id)
    if not case:
        return {"error": f"No case {case_id} in the docket"}
    return {"case": {k: v for k, v in case.items() if not k.startswith("_")},
            "priority": {"score": case.get("_score"), "band": case.get("_band"), "flags": case.get("_flags"),
                         "route": case.get("_route")}}


def _priority_cases(band: str = "Critical", flag: str = "", limit: int = 15) -> Dict:
    with _session() as s:
        rows = s.select("cases", {"status": "pending", **({"band": band} if band else {})}, order="score DESC")
    sel = [r for r in rows if not flag or flag in (r["flags"] or [])][:limit]
    return {"count": len(sel), "cases": [{"case_id": r["case_id"], "score": r["score"], "band": r["band"],
                                          "flags": r["flags"], "route": r["route"]} for r in sel]}


def _deferral_report(limit: int = 20) -> Dict:
    """Cases past their listing deadline and cases deferred 3+ times in a row, with the last reason."""
    today = date.today().isoformat()
    with _session() as s:
        states = s.select("case_queue_state")
        bands = {r["case_id"]: r["band"] for r in s.select("cases", {"status": "pending"})}
    rows = [st for st in states if st["case_id"] in bands]
    past = sorted((r for r in rows if r["sla_due_on"] and r["sla_due_on"] < today), key=lambda r: r["sla_due_on"])
    deferred = sorted((r for r in rows if (r["consecutive_deferrals"] or 0) >= 3), key=lambda r: -(r["consecutive_deferrals"] or 0))
    fmt = lambda r: {"case_id": r["case_id"], "band": bands.get(r["case_id"]), "sla_due_on": r["sla_due_on"],  # noqa: E731
                     "consecutive_deferrals": r["consecutive_deferrals"], "last_reason": r["last_deferral_reason"],
                     "must_list": r["must_list"]}
    return {"past_deadline": len(past), "deferred_3_plus": len(deferred), "past_deadline_cases": [fmt(r) for r in past[:limit]],
            "deferred_cases": [fmt(r) for r in deferred[:limit]], "screen": "/staff/docket?filter=deferred"}


def _prepare_cause_list(start_date: str = "", days: int = 5, _ctx: Optional[Dict] = None) -> Dict:
    """Builds a DRAFT list (nothing is published) and hands over to the Cause list screen for the Registrar."""
    from .. import cause_list
    today = date.today()
    start = date.fromisoformat(start_date) if start_date else today + timedelta(days=(7 - today.weekday()) % 7 or 7)
    with _session() as s:
        plan = cause_list.prepare(s, start, int(days))
        cid = cause_list.save_draft(s, plan, explanation=f"Draft prepared from Nyaya Mitra by {(_ctx or {}).get('actor', 'staff')}")
    m = plan["metrics"]
    return {"cause_list_id": cid, "status": "draft - awaiting Registrar approval", "start_date": start.isoformat(),
            "listed": m["cases_listed"], "carried_over": m["cases_carried_over"], "utilisation_percent": m["avg_bench_utilisation_percent"],
            "must_list": m["must_list_total"], "capacity_shortfall": bool(plan["capacity_shortfall"]),
            "deadline_alerts": len(plan["deadline_alerts"]), "violations": len(plan["violations"]),
            "actions": [{"label": "Open Cause list", "route": f"/staff/cause-lists/{cid}", "prefill": {"cause_list_id": cid}}]}


def _get_case_status(case_number: str, filing_date: str = "", filing_year: str = "") -> Dict:
    """Citizen view, after verification (case number + filing date or year): stage and next hearing only."""
    from .. import store
    fail = {"verified": False, "message": "Could not verify these details. Check the case number and filing year on your "
                                          "papers, or ask at the court's help desk."}
    case = store.get_case((case_number or "").strip())
    if not case or not case.get("filing_date"):
        return fail  # same message whether the case exists or not
    if filing_date:
        verified = store._iso_date(filing_date) == case["filing_date"]
    else:
        verified = bool(filing_year) and str(filing_year).strip() == case["filing_date"][:4]
    if not verified:
        return fail
    return {"verified": True, "stage": (case.get("stage") or "not recorded").replace("_", " "),
            "next_hearing_date": case.get("next_hearing_date") or "not yet fixed"}


def _classify_and_prioritise(description: str) -> Dict:
    c = triage.classify_free_text(description)
    case = {"case_id": "INTAKE", "filing_date": date.today().isoformat(), "adjournments": 0, "advocate_ids": [], **c}
    return {"classification": c, "priority": triage.score_case(case)}


def _settlement_options(case_type: str) -> Dict:
    route = triage.ADR_ROUTES.get(case_type)
    return {"case_type": case_type, "adr_route": route,
            "lok_adalat": "No court fee; award is final and binding; court fee already paid is refunded when a pending case is settled.",
            "suitable": bool(route)}


def _draft_document(section: str, context: str, instructions: str = "") -> Dict:
    return drafting.draft(section, context, instructions)


# ----------------------------------------------------------------------------- the registry
LEGAL_AID_ARGS = ("woman, child, sc_st, disability, in_custody, industrial_workman, trafficking_victim, "
                  "disaster_victim (bools), annual_income (number, per year), court_level ('district'|'high_court'|'supreme_court'), "
                  "district (str), state (str), language (str)")

REGISTRY: List[Tool] = [
    Tool("check_legal_aid_eligibility", "Decide eligibility for FREE legal aid under Sec. 12 LSA Act (likely / possibly / not on the facts) and where to go.",
         LEGAL_AID_ARGS, _check_legal_aid),
    Tool("draft_legal_aid_application", "Draft the application to the Legal Services Authority; offers a Word download.",
         "problem (str), language, plus eligibility fields", _draft_legal_aid_application, screen="/citizen/legal-aid"),
    Tool("find_legal_aid_office", "Nearest legal services office (DLSA) by district, with phone and address; dated web fallback.",
         "district (str), state (str)", _find_legal_aid_office),
    Tool("legal_aid_kb_search", "Explain legal-aid procedures, rights and schemes (Lok Adalat, how to apply, who is eligible) with cited passages; prefer primary sources and say when only secondary ones were found.",
         "query (str), top_k (int)", _legal_aid_kb_search),
    Tool("state_legal_aid_fact", "Current State fact (income limit for free legal aid, helpline) with its source and the date it was checked.",
         "state (str), key ('income_limit'|'helpline')", _state_legal_aid_fact),
    Tool("check_undertrial_release", "Compute whether a person in custody has crossed the Sec. 479 BNSS release threshold.",
         "custody_since (YYYY-MM-DD), max_sentence_years (number|'life'), first_time_offender (bool), offence (str: the charge in the person's words, e.g. 'murder', 'theft')", _check_undertrial_release),
    Tool("request_release_review", "Send the custody facts to a legal-aid lawyer, who reviews and decides on a Sec. 479 application.",
         "custody_since (YYYY-MM-DD), max_sentence_years, first_time_offender (bool), description (str), case_number (str)",
         _request_release_review, roles=(CITIZEN, LAWYER), has_side_effects=True, needs_approval=True, screen="/lawyer/alerts",
         confirm_question="Shall I send these facts to a legal-aid lawyer for review? (yes / no)", wants_ctx=True),
    Tool("analyze_document", "Read the file(s) attached in this chat: plain-language summary and deadlines (staff: brief, priority, Open case).",
         "batch_id (str, given when files are attached)", _analyze_document, needs_file=True, wants_ctx=True),
    Tool("explain_document", "Get the stored summary of a document analysed earlier.", "doc_id (str)", _explain_document),
    Tool("get_case_status", "Stage and next hearing date of a court case, after verifying the case number and filing year.",
         "case_number (str), filing_year (str) or filing_date (YYYY-MM-DD)", _get_case_status, roles=(CITIZEN,)),
    Tool("classify_and_prioritise", "Classify a described dispute into a case type and urgency.", "description (str)",
         _classify_and_prioritise, roles=(CITIZEN, LAWYER)),
    Tool("settlement_options", "Whether the dispute can go to Lok Adalat / mediation and what that means.", "case_type (str)",
         _settlement_options),
    Tool("search_law", "Search the curated knowledge base of Indian statutes, NALSA schemes and judgments.", "query (str), top_k (int)",
         _search_law),
    Tool("web_search", "Search official government / court websites for current facts (results carry the date checked).",
         "query (str)", _web_search),
    Tool("get_undertrial_alerts", "List Undertrial Watch alerts (read-only).", "status ('pending'|'approved'|...), limit (int)",
         _get_undertrial_alerts, roles=COURT, screen="/lawyer/alerts"),
    Tool("draft_document", f"Draft a pleading section. Sections: {list(drafting.SECTIONS)}.", "section, context, instructions",
         _draft_document, roles=COURT),
    # No lookup_case / docket tools for citizens: they return full records (advocate ids included). Staff-only.
    Tool("priority_cases", "List the highest-priority pending cases, optionally by band or flag (e.g. UNDERTRIAL_RELEASE_ELIGIBLE).",
         "band (str), flag (str), limit (int)", _priority_cases, roles=(STAFF,), screen="/staff/docket"),
    Tool("lookup_case", "Fetch a case and its priority explanation.", "case_id (str)", _lookup_case, roles=(STAFF,)),
    Tool("deferral_report", "Cases past their listing deadline and cases deferred 3+ times, with reasons.", "limit (int)",
         _deferral_report, roles=(STAFF,), screen="/staff/docket?filter=deferred"),
    Tool("prepare_cause_list", "Build next week's DRAFT cause list (key numbers) and open the Cause list screen; the Registrar approves there.",
         "start_date (YYYY-MM-DD, optional), days (int)", _prepare_cause_list, roles=(STAFF,), has_side_effects=True,
         needs_approval=True, screen="/staff/cause-lists",
         confirm_question="Shall I prepare a draft cause list for next week? Nothing is published until the Registrar approves. (yes / no)",
         wants_ctx=True),
]
BY_NAME = {t.name: t for t in REGISTRY}


def tools_for(role: str) -> List[Tool]:
    return [t for t in REGISTRY if role in t.roles]


CITIZEN_TOOLS = tools_for(CITIZEN)
LAWYER_TOOLS = tools_for(LAWYER)
STAFF_TOOLS = tools_for(STAFF)
