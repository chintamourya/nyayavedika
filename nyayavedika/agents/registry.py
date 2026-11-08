"""Registry Agent - weekly cause-list preparation with human sign-off.

    START -> triage -> review -> schedule -> explain -> approve [interrupt: registrar] -> publish -> END

* triage   : transparent rule-based scores for the whole docket (nyayavedika.triage)
* review   : the LLM inspects edge cases the rules can miss (custody without dates, very old cases
             at early stages, contradictory fields) and proposes bounded adjustments (±10) with reasons
             and data requests - every adjustment is logged, never silent
* schedule : priority + adjournment-aware + conflict-free cause list (nyayavedika.scheduler)
* explain  : a registrar's note: what changed vs FIFO, who is listed first and why
* approve  : human-in-the-loop; nothing is published without the registrar

Phase 5: triage re-scores only changed cases and reads pending cases + queue state from the tables
(nyayavedika.cause_list); schedule uses the memory-aware planner and its invariants; publish writes listings,
hearings, next hearing dates and audit_log. LangGraph is imported lazily.
"""
import logging
from datetime import date
from typing import Dict, List, Optional, TypedDict

from .. import cause_list, impact, llm, store, triage
from .. import config
from ..models import RegistryReview

logger = logging.getLogger(__name__)
MAX_REVIEW = config.REGISTRY_MAX_REVIEW


class RegistryState(TypedDict, total=False):
    court_id: Optional[str]
    start_date: str
    days: int
    benches: Optional[List[dict]]
    results: List[dict]
    review: dict
    plan: dict
    explanation: str
    cause_list_id: int
    decision: dict


REVIEW_SYSTEM = """You review an Indian district court's rule-based case priorities before the weekly cause list.
Look ONLY for cases where the rules are likely wrong because of data problems or context the rules miss, e.g.
custody cases without custody dates, 10+ year cases stuck at admission/notice, bail matters pending for weeks,
senior citizens in execution proceedings. Propose an adjustment between -10 and +10 with a one-line reason,
and list missing data the registry should collect. Do not adjust cases that look fine. Be conservative."""

EXPLAIN_SYSTEM = """Write a short note (max 180 words) for the Registrar approving this week's cause list:
what the list prioritises, how it compares with the oldest-first list (use the numbers), data issues to fix,
and any undertrial release cases needing immediate attention. Plain, formal English. No markdown headings."""


def _odd(r: dict) -> bool:
    c = r["case"]
    return ((c.get("accused_in_custody") and not (c.get("custody_since") and c.get("max_sentence_years")))
            or ("DECADE_OLD" in r["flags"] and c.get("stage") in ("admission", "notice", "pleadings"))
            or "UNDERTRIAL_NEARING_THRESHOLD" in r["flags"])


def triage_node(state: RegistryState) -> dict:
    with store.connect() as s:
        store.ensure_database(s)  # migrated at start-up; re-run only if the schema is gone
        rescored = cause_list.score_changed(s)
        triage.load_adjournment_rates(cause_list.learned_rates(s))
        results = cause_list.pending_results(s, state.get("court_id"))
    impact.record("case_triaged", rescored)
    for r in results:
        if any(k in r["recommended_route"] for k in ("Lok Adalat", "Mediation", "mediation", "Conciliation", "compounding")):
            impact.record("adr_candidate", route=r["recommended_route"].split(" (")[0])
    return {"results": results}


def review_node(state: RegistryState) -> dict:
    odd = [r for r in state["results"] if _odd(r)][:MAX_REVIEW]
    if not odd or not llm.available():
        notes = [f"{r['case_id']}: custody case missing custody date / max sentence" for r in odd
                 if r["case"].get("accused_in_custody") and not r["case"].get("custody_since")]
        return {"review": {"adjustments": [], "data_quality_notes": notes, "engine": "rules"}}
    brief = "\n".join(f"{r['case_id']} | score {r['score']} {r['band']} | flags {r['flags']} | "
                      f"{ {k: r['case'].get(k) for k in ('case_type', 'stage', 'filing_date', 'adjournments', 'accused_in_custody', 'custody_since', 'max_sentence_years', 'senior_citizen')} }"
                      for r in odd)
    rev = llm.structured(REVIEW_SYSTEM, brief, RegistryReview, fast=True).model_dump()
    by_id = {r["case_id"]: r for r in state["results"]}
    applied = []
    for adj in rev["adjustments"]:
        r = by_id.get(adj["case_id"])
        if not r:
            continue
        delta = max(-10, min(10, int(adj["adjustment"])))
        r["score"] = round(min(100, max(0, r["score"] + delta)), 1)
        r["reasons"].append(f"AI review {delta:+d}: {adj['reason']}")
        if "UNDERTRIAL_RELEASE_ELIGIBLE" not in r["flags"]:
            r["band"] = "Critical" if r["score"] >= 60 else "High" if r["score"] >= 45 else "Medium" if r["score"] >= 30 else "Routine"
        applied.append({**adj, "adjustment": delta})
    if applied:  # every AI adjustment is logged with its reason in the score history
        with store.connect() as s:
            s.insert("triage_scores", [{"case_id": a["case_id"], "score": by_id[a["case_id"]]["score"],
                                        "band": by_id[a["case_id"]]["band"], "flags": by_id[a["case_id"]]["flags"],
                                        "reasons": by_id[a["case_id"]]["reasons"], "rules_version": triage.RULES_VERSION,
                                        "ai_adjustment": a["adjustment"], "ai_reason": a["reason"]} for a in applied])
    results = sorted(state["results"], key=lambda r: r["score"], reverse=True)
    return {"results": results, "review": {"adjustments": applied, "data_quality_notes": rev["data_quality_notes"], "engine": "llm"}}


def schedule_node(state: RegistryState) -> dict:
    start = date.fromisoformat(state["start_date"]) if state.get("start_date") else date.today()
    with store.connect() as s:
        plan = cause_list.prepare(s, start, int(state.get("days") or 5), state.get("court_id"), results=state["results"])
    return {"plan": plan}


def explain_node(state: RegistryState) -> dict:
    m = state["plan"]["metrics"]
    rel = sum(1 for r in state["results"] if "UNDERTRIAL_RELEASE_ELIGIBLE" in r["flags"])
    facts = {"metrics": m, "undertrials_release_eligible": rel, "review": state.get("review")}
    if llm.available():
        try:
            return {"explanation": llm.text(EXPLAIN_SYSTEM, str(facts), fast=True)}
        except Exception as exc:
            logger.warning("explain failed: %s", exc)
    b = m["baseline_fifo"]
    return {"explanation": (
        f"This list schedules {m['cases_listed']} matters; all {m['critical_listed']} of {m['critical_total']} critical "
        f"matters are listed with an average wait of {m['critical_avg_wait_days']} working days (oldest-first list: "
        f"{b['critical_avg_wait_days']}). Advocate double-bookings: {m['advocate_conflicts']} (oldest-first: "
        f"{b['advocate_conflicts']}). Expected effective hearings: {m['expected_effective_hearings']} vs {b['expected_effective_hearings']}. "
        f"{rel} undertrial(s) appear entitled to release under Sec. 479 BNSS and need immediate attention.")}


def save_draft(state: RegistryState) -> dict:
    with store.connect() as s:
        cid = cause_list.save_draft(s, state["plan"], state.get("court_id") or "DEMO-DC", state["explanation"])
    return {"cause_list_id": cid}


def approve_node(state: RegistryState) -> dict:
    from langgraph.types import interrupt
    decision = interrupt({"type": "approve_cause_list", "cause_list_id": state["cause_list_id"],
                          "metrics": state["plan"]["metrics"], "explanation": state["explanation"],
                          "review": state.get("review")})
    return {"decision": decision if isinstance(decision, dict) else {"approve": bool(decision)}}


def publish_node(state: RegistryState) -> dict:
    d = state["decision"]
    actor, role = d.get("actor") or "registrar", d.get("role") or "staff"
    with store.connect() as s:
        if d.get("approve"):
            cause_list.publish(s, state["cause_list_id"], actor, role)
        else:
            cause_list.reject(s, state["cause_list_id"], actor, role, d.get("note", ""))
    return {}


_graph = None


def graph():
    global _graph
    if _graph is None:
        from langgraph.graph import END, START, StateGraph
        from .checkpoint import get_checkpointer
        g = StateGraph(RegistryState)
        nodes = [("triage", triage_node), ("review", review_node), ("schedule", schedule_node),
                 ("explain", explain_node), ("save_draft", save_draft), ("approve", approve_node), ("publish", publish_node)]
        for name, fn in nodes:
            g.add_node(name, fn)
        g.add_edge(START, "triage")
        for (a, _), (b, _) in zip(nodes, nodes[1:]):
            g.add_edge(a, b)
        g.add_edge("publish", END)
        _graph = g.compile(checkpointer=get_checkpointer())
    return _graph
