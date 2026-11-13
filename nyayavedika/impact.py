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
  api_usage_<door>_<feature>_* one API action; value = server milliseconds; door/feature/status_code in event/meta
  door_visit_<door>           one portal page visit; no visitor identity
"""
import csv
import io
import logging
from pathlib import Path
from typing import Any, Dict, Optional

from . import config

logger = logging.getLogger(__name__)
PILOT_LOG_PATH = Path(__file__).resolve().parents[1] / "pilot" / "pilot_log.csv"

API_FEATURES = {
    "agent": "assistant_chat",
    "advocate": "document_tools",
    "documents": "document_tools",
    "legal-aid": "legal_aid",
    "legal-problem": "legal_problem_chat",
    "undertrial": "undertrial_watch",
    "alerts": "undertrial_alerts",
    "triage": "court_operations",
    "registry": "court_operations",
    "cause-lists": "court_operations",
    "schedule": "court_operations",
    "cases": "court_operations",
    "hearings": "court_operations",
    "docket": "court_operations",
    "today": "court_operations",
    "insights": "court_operations",
    "intake": "court_operations",
    "jobs": "court_operations",
    "draft": "legal_work",
    "summarize": "legal_work",
}


def api_feature(route_path: str, method: str = "GET", door: str = "unknown") -> Optional[str]:
    """Map a FastAPI route template to a user-facing tool name, never a request URL."""
    parts = route_path.strip("/").split("/")
    if len(parts) < 2 or parts[0] != "api" or parts[1] in {
        "health", "impact", "feedback", "field-feedback", "whoami", "impact-reports"
    }:
        return None
    root = parts[1]
    tail = parts[2:]
    if root == "advocate":
        if tail[:1] == ["studio"]:
            return "document_studio"
        if tail[:1] == ["documents"]:
            if len(tail) == 1:
                return "document_upload"
            action = tail[2] if len(tail) > 2 else ""
            return {
                "preview": "document_preview",
                "insights": "document_insights",
                "chat": "document_chat",
                "prepare": "document_chat_prepare",
            }.get(action, "document_tools")
        return "document_tools"
    if root == "documents":
        return {"analyze": "document_analysis", "summarize": "document_summary"}.get(
            tail[0] if tail else "", "document_tools"
        )
    if root == "legal-problem":
        return "legal_problem_research" if tail[:1] == ["research"] else "legal_problem_chat"
    if root == "legal-aid":
        action = tail[0] if tail else ""
        if action in ("application.docx",):
            return "legal_aid_application"
        if action in ("ask", "explain"):
            return "legal_aid_guidance"
        return "legal_aid_check"
    if root == "undertrial":
        return "undertrial_scan"
    if root == "alerts":
        action = tail[1] if len(tail) > 1 else ""
        return "undertrial_decision" if action in ("state", "decide") else "undertrial_alerts"
    if root == "cause-lists":
        return "cause_list_publish" if "publish" in tail else "cause_list_planning"
    if root == "triage":
        return "case_triage"
    if root == "registry":
        return "registry_agent"
    if root == "schedule":
        return "schedule_preview"
    if root == "intake":
        return "case_intake"
    if root == "cases":
        return "case_management"
    if root == "hearings":
        return "hearing_management"
    if root == "jobs":
        return "staff_jobs"
    if root == "draft":
        return "legal_drafting"
    if root == "summarize":
        return "offline_summarization"
    if root in ("today", "docket", "insights"):
        return {"today": "daily_brief", "docket": "docket_view", "insights": "weekly_insights"}[root]
    if root == "agent":
        return {"citizen": "citizen_assistant", "advocate": "advocate_assistant", "staff": "staff_assistant"}.get(
            door, "assistant_chat"
        )
    return API_FEATURES.get(root)


def api_door(route_path: str, method: str, authorization: Optional[str], role_hint: Optional[str]) -> str:
    """Resolve the portal from the authenticated role and the route's actual role policy."""
    from . import auth
    roles = auth.POLICY.get(f"{method.upper()} {route_path}")
    if not roles:
        return "unknown"
    try:
        principal = auth.check(authorization, *roles, role_hint=role_hint)
    except auth.AuthError:
        return "unknown"
    return {"citizen": "citizen", "lawyer": "advocate", "staff": "staff"}.get(principal.role, "unknown")


def record_door_visit(door: str) -> None:
    if door in ("citizen", "advocate", "staff"):
        record(f"door_visit_{door}")


def reach_hash(browser_id: str) -> str:
    """Validate a browser-generated UUID and store only a deterministic pseudonymous digest."""
    import hashlib
    import uuid
    parsed = uuid.UUID(browser_id)
    if parsed.version != 4 or str(parsed) != browser_id.lower():
        raise ValueError("browser_id must be a canonical UUID v4")
    return hashlib.sha256(b"nyayavedika-reach-v1:" + parsed.bytes).hexdigest()


def record_browser_activity(browser_id: str, door: str, feature: str) -> None:
    if door not in ("citizen", "advocate", "staff") or not feature or len(feature) > 64:
        return
    try:
        visitor_hash = reach_hash(browser_id)
    except (ValueError, AttributeError, TypeError):
        return
    try:
        from . import db
        db.register_browser_feature(visitor_hash, door, feature)
    except Exception as exc:  # analytics must never interrupt an application request
        logger.warning("impact.browser_activity(%s, %s) failed: %s", door, feature, exc)


def record_api_usage(door: str, feature: str, method: str, status_code: int, duration_ms: float) -> None:
    if door not in ("citizen", "advocate", "staff", "unknown") or not feature or len(feature) > 32:
        return
    result = "success" if status_code < 400 else "failure"
    record(f"api_usage_{door}_{feature}_{result}", max(0.0, float(duration_ms)),
           method=method, status_code=int(status_code), door=door, feature=feature)


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
    browser_activity = db.browser_feature_totals()
    usage_groups: Dict[str, Dict[str, Dict[str, float]]] = {}
    doors = ("citizen", "advocate", "staff", "unknown", "unattributed")
    for event, values in t.items():
        if not event.startswith("api_usage_"):
            continue
        parts = event.split("_")
        result = parts[-1]
        if result not in ("success", "failure"):
            continue
        middle = "_".join(parts[2:-1])
        door = next((name for name in doors[:-1] if middle.startswith(f"{name}_")), None)
        if door:
            feature = middle[len(door) + 1:]
        else:
            # Include historical feature-only events in combined totals, but don't guess their door.
            door, feature = "unattributed", middle
        bucket = usage_groups.setdefault(door, {}).setdefault(feature, {"requests": 0, "successful": 0, "failed": 0, "duration_ms": 0.0})
        bucket["requests"] += values.get("count", 0)
        bucket["successful" if result == "success" else "failed"] += values.get("count", 0)
        bucket["duration_ms"] += values.get("total", 0.0)

    def usage_row(features: Dict[str, Dict[str, float]], unique_browsers: int = 0,
                  feature_browsers: Optional[Dict[str, int]] = None) -> Dict[str, Any]:
        requests = sum(row["requests"] for row in features.values())
        successes = sum(row["successful"] for row in features.values())
        failures = sum(row["failed"] for row in features.values())
        duration = sum(row["duration_ms"] for row in features.values())
        return {
            "requests": requests, "successful": successes, "failed": failures,
            "unique_browsers": unique_browsers,
            "avg_server_ms": round(duration / requests, 1) if requests else None,
            "features": {
                feature: {**{k: row[k] for k in ("requests", "successful", "failed")},
                          "unique_browsers": (feature_browsers or {}).get(feature, 0),
                          "avg_server_ms": round(row["duration_ms"] / row["requests"], 1) if row["requests"] else None}
                for feature, row in sorted(features.items())
            },
        }

    for door in ("citizen", "advocate", "staff", "unknown"):
        usage_groups.setdefault(door, {})
    by_door = {
        door: usage_row(
            features,
            browser_activity["by_door"].get(door, 0),
            browser_activity["by_door_feature"].get(door, {}),
        )
        for door, features in sorted(usage_groups.items())
    }
    by_feature: Dict[str, Dict[str, float]] = {}
    for features in usage_groups.values():
        for feature, row in features.items():
            target = by_feature.setdefault(feature, {"requests": 0, "successful": 0, "failed": 0, "duration_ms": 0.0})
            for key in ("requests", "successful", "failed", "duration_ms"):
                target[key] += row[key]
    feature_rows = {
        feature: {**{k: row[k] for k in ("requests", "successful", "failed")},
                  "unique_browsers": browser_activity["by_feature"].get(feature, 0),
                  "avg_server_ms": round(row["duration_ms"] / row["requests"], 1) if row["requests"] else None}
        for feature, row in sorted(by_feature.items())
    }
    door_visits = {door: count(f"door_visit_{door}") for door in ("citizen", "advocate", "staff")}
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
        "door_visits": {"total": sum(door_visits.values()), "by_door": door_visits},
        "reach": db.reach_totals(),
        "api_usage": {
            "total": usage_row(by_feature, browser_activity["unique_browsers"], browser_activity["by_feature"]),
            "by_door": by_door,
            "by_feature": feature_rows,
        },
        "assumptions": {"minutes_per_page_read": config.MINUTES_PER_PAGE_READ},
        "note": "Citizen sessions are not unique people. Distinct-browser counts use a persistent random browser ID; people "
                "using multiple browsers may be counted more than once. API requests "
                "are activity counts, not completed outcomes; server response time is not end-to-end task time. Feedback "
                "outcomes and task times are voluntary self-reports unless separately verified. Review case sources before "
                "reporting case totals as field outcomes.",
    }


def demo_summary() -> Dict[str, Any]:
    """Public-safe aggregate metrics for the demo API; never include individual records."""
    from . import feedback, store
    report = summary()
    with store.connect() as session:
        feedback.ensure_table(session)
        survey = feedback.summarise(session.select("field_feedback"), suppress_small_timing_sample=True)
    if PILOT_LOG_PATH.is_file():
        from . import pilot_metrics
        pilot_rows = pilot_metrics.read_csv(PILOT_LOG_PATH)
        pilot = {"available": bool(pilot_rows), **pilot_metrics.summarise(pilot_rows)}
        if not pilot_rows:
            pilot["message"] = "Pilot log has no case rows yet. Add anonymized data to pilot/pilot_log.csv."
    else:
        pilot = {
            "available": False,
            "message": "No pilot log yet. Add anonymized paired pilot data using pilot/pilot_log_template.csv.",
            "cases_screened": 0,
            "lawyer_checked": 0,
            "precision": None,
            "recall": None,
            "median_manual_minutes": None,
            "median_tool_minutes": None,
            "median_minutes_saved": None,
            "median_time_saved_pct": None,
            "cases_with_timing": 0,
            "flagged_for_release": 0,
            "people_held_past_limit": 0,
            "days_over_limit_total": 0,
            "applications_filed": 0,
            "released": 0,
            "denied": 0,
            "pending": 0,
        }
    return {
        "reach": report["reach"],
        "door_visits": report["door_visits"],
        "api_usage": report["api_usage"],
        "product": {
            "citizen_sessions": report["people_reached"],
            "legal_aid_checks": report["legal_aid"]["eligibility_checks"],
            "legal_aid_applications_drafted": report["legal_aid"]["applications_drafted"],
            "documents_analyzed": report["documents"]["analyzed"],
            "undertrials_flagged": report["undertrials"]["flagged"],
            "release_applications_approved": report["undertrials"]["release_applications_approved"],
            "cases_triaged": report["registry"]["cases_triaged"],
            "cause_lists_published": report["registry"]["cause_lists_published"],
            "cases_listed": report["registry"]["cases_listed"],
        },
        "feedback": {
            "responses": survey["responses"],
            "avg_rating": survey["avg_rating"],
            "outcome_changed_pct": survey["outcome_changed_pct"],
            "would_recommend_pct": survey["would_recommend_pct"],
            "task_timing": survey["task_timing"],
        },
        "pilot_comparison": pilot,
        "disclaimer": (
            "Aggregated user activity. Distinct-browser counts use a random persistent browser identifier; they estimate "
            "browsers. Activity records do not include names, contact details, IP addresses, request "
            "text, or uploaded-document contents. Feedback outcomes are voluntary self-reports. Check source records before "
            "reporting case or outcome totals as field impact."
        ),
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
