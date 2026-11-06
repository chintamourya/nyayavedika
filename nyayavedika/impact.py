"""Impact instrumentation - the evidence base for "Proven impact".

Every agent records outcome events to Postgres (impact_events). /api/impact aggregates them into
the numbers a submission or a DLSA / court partner report needs, and /api/impact/export.csv
produces the raw log. Events never contain personal data.

Event catalogue (value = count unless noted):
  citizen_session            one conversation (or one form submission) - counted once, not per message;
                             meta.channel = chat | form. Not unique people: the portal has no login.
  assistant_session          a court user started a conversation with the assistant
  legal_aid_check            eligibility checked;          meta.eligible
  legal_aid_application      application drafted
  legal_aid_outcome          partner-reported outcome;     meta.status (applied / lawyer_assigned)
  document_analyzed          value = pages;                meta.ocr_pages, meta.verified
  undertrial_flagged         custody case past / near Sec. 479 BNSS threshold
  release_application_approved   human-approved draft sent to DLSA / jail lawyer
  case_triaged               value = cases scored
  adr_candidate              case routed to Lok Adalat / mediation
  cause_list_published       value = cases listed;         meta.conflicts_avoided, meta.critical_wait_gain
  feedback                   value = rating 1-5
  decision                   human decision;               meta.actor, meta.role, meta.action, meta.entity
"""
import csv
import io
import logging
from typing import Any, Dict, Optional

from . import config

logger = logging.getLogger(__name__)


def record(event: str, value: float = 1.0, **meta: Any) -> None:
    try:
        from . import db
        db.insert(db.impact_events, event=event, value=float(value), meta=meta or None)
    except Exception as exc:  # metrics must never break a user-facing flow
        logger.warning("impact.record(%s) failed: %s", event, exc)


def summary() -> Dict:
    from . import db
    t = db.event_totals()

    def total(e):
        return t.get(e, {}).get("total", 0.0)

    def count(e):
        return t.get(e, {}).get("count", 0)

    pages = total("document_analyzed")
    eligible = [r for r in db.fetch(db.legal_aid_requests, limit=100000) if r["eligible"]]
    ratings = t.get("feedback", {})
    return {
        # Sessions only. Eligibility checks made inside a chat belong to that session, so they are not added on top.
        "people_reached": count("citizen_session"),
        "legal_aid": {
            "eligibility_checks": count("legal_aid_check"),
            "found_eligible": len(eligible),
            "applications_drafted": count("legal_aid_application"),
            "lawyers_assigned_reported": sum(1 for r in eligible if r["status"] == "lawyer_assigned"),
        },
        "documents": {
            "analyzed": count("document_analyzed"),
            "pages": int(pages),
            "reading_hours_saved_est": round(pages * config.MINUTES_PER_PAGE_READ / 60, 1),
        },
        "undertrials": {
            "flagged": count("undertrial_flagged"),
            "release_applications_approved": count("release_application_approved"),
        },
        "registry": {
            "cases_triaged": int(total("case_triaged")),
            "adr_candidates": count("adr_candidate"),
            "cause_lists_published": count("cause_list_published"),
            "cases_listed": int(total("cause_list_published")),
        },
        "feedback": {
            "responses": ratings.get("count", 0),
            "avg_rating": round(ratings["total"] / ratings["count"], 2) if ratings.get("count") else None,
        },
        "assumptions": {"minutes_per_page_read": config.MINUTES_PER_PAGE_READ},
        "note": "people_reached counts citizen sessions (a chat or a form submission), not unique individuals: the portal "
                "needs no login. Figures from a demo or seeded database are not field results.",
    }


def export_csv(limit: Optional[int] = 100000) -> str:
    from . import db
    rows = db.fetch(db.impact_events, limit=limit, order=db.impact_events.c.id)
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["id", "timestamp_utc", "event", "value", "meta"])
    for r in rows:
        w.writerow([r["id"], r["ts"].isoformat() if r["ts"] else "", r["event"], r["value"], r["meta"] or ""])
    return buf.getvalue()
