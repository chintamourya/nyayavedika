"""Demo API on the Python standard library, for machines without the full requirements (no FastAPI / LangGraph).

    python scripts/dev_api.py [--port 8010] [--no-worker] [--seed 120]

Serves the staff app (/staff), advocate door (/advocate), citizen portal (/citizen) and the /api routes the UI uses, with the SAME
role checks (nyayavedika.auth.POLICY) and the SAME nyayavedika functions as server.py - no separate business logic.
Differences: the assistant is the offline FrontDoor (no LLM graph), and the intake worker runs in a background
thread. Use `python server.py` + `python -m nyayavedika.worker` where the requirements are installed.
"""
import argparse
import base64
import binascii
import json
import re
import sys
import threading
import time
import uuid
from datetime import date, datetime, timezone
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
# nyayavedika.config reads .env on import.
from nyayavedika import (advocate, auth, cause_list, feedback, config, db, demo_seed, document_studio, impact, intake, jobs, legal_aid, legal_aid_kb, legal_problem, ocr, staff_api,  # noqa: E402
                   store, summarise, worker, public_docs)
from nyayavedika.agents import undertrial_watch  # noqa: E402
from nyayavedika import impact_reports  # noqa: E402
from nyayavedika.agents.front_door import FrontDoor, answer_kind  # noqa: E402
from nyayavedika.docgen import legal_aid_docx  # noqa: E402

STATIC = ROOT / "static"
DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
THREADS = {}  # thread_id -> FrontDoor state (offline assistant)


class HttpError(Exception):
    def __init__(self, status, detail):
        super().__init__(str(detail))
        self.status, self.detail = status, detail


def _db(fn, *a, **k):
    with store.connect() as s:
        return fn(s, *a, **k)


def _guard(handler, key):
    try:
        return auth.check(handler.headers.get("Authorization"), *auth.POLICY[key])
    except auth.AuthError as exc:
        raise HttpError(exc.status, exc.message)


def _intake(fn, *a):
    try:
        return fn(*a)
    except intake.IntakeError as exc:
        raise HttpError(exc.status, {"message": exc.message, "files": exc.files} if exc.files else exc.message)


def _court(fn, *a):
    try:
        return _db(fn, *a)
    except LookupError as exc:
        raise HttpError(404, str(exc))
    except (legal_problem.InvalidResearchInput, ValueError) as exc:   # as server.py: bad input is a 400, not a crash
        raise HttpError(400, str(exc))


def _multipart(handler, body):
    msg = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: " + handler.headers["Content-Type"].encode() + b"\r\n\r\n" + body)
    fields, files = {}, []
    for part in msg.iter_parts():
        name = part.get_param("name", header="content-disposition")
        if part.get_filename() is not None:
            files.append((part.get_filename(), part.get_payload(decode=True) or b""))
        else:
            fields.setdefault(name, []).append(part.get_content().strip())
    return fields, files


def _chat(principal, message, thread_id, batch_id=None):
    role = principal.role
    thread_id = thread_id or f"{role}-{uuid.uuid4().hex[:12]}"
    if not thread_id.startswith(f"{role}-"):
        raise HttpError(403, "This conversation belongs to a different role")
    if thread_id not in THREADS:  # one session per conversation, as in server.py
        impact.record("citizen_session" if role == "citizen" else "assistant_session", role=role, channel="chat", engine="offline")
    out = FrontDoor(role, principal.actor).handle(message, THREADS.get(thread_id), batch_id)
    THREADS[thread_id] = out["state"]
    kind = answer_kind((out["state"] or {}).get("awaiting"))
    return {"thread_id": thread_id, "reply": out["reply"], "actions": out["actions"], "answer_kind": kind,
            "awaiting_confirmation": kind == "confirm", "awaiting_answer": kind is not None,
            "steps": [{"action": t} for t in out["tools_used"]]}


def _docx_name(prefix, label):
    return f'{prefix}_{re.sub(r"[^A-Za-z0-9]+", "_", label or "district").strip("_") or "district"}_{date.today().isoformat()}.docx'


def _document_pages(d):
    filename = d.get("filename") or "document.txt"
    suffix = Path(filename).suffix.lower().lstrip(".")
    if suffix not in config.ALLOWED_EXTS:
        raise HttpError(400, f"File type .{suffix or '(none)'} is not accepted")
    if d.get("content_base64"):
        try:
            data = base64.b64decode(d["content_base64"], validate=True)
        except (ValueError, binascii.Error):
            raise HttpError(400, "The uploaded file is not valid base64")
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HttpError(413, "File too large")
        pages = ocr.extract(data, filename)
        size = len(data)
    elif (d.get("text") or "").strip():
        data = d["text"].encode("utf-8")
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HttpError(413, "Text is too large")
        pages = [{"page": 1, "text": d["text"], "source": "text", "confidence": None}]
        size = len(data)
    else:
        raise HttpError(400, "Send a file or document text")
    if len(pages) > min(config.DEMO_MAX_PAGES, 50):
        raise HttpError(413, "Document exceeds the 50-page-per-file limit")
    if not any((page.get("text") or "").strip() for page in pages):
        raise HttpError(400, "No readable text found in the document")
    return filename, pages, size


# (method, path regex, POLICY key or None for public, handler(h, m, q, body) -> dict | (bytes, type, filename))
def routes():
    R = []

    def r(method, pattern, key=None):
        def deco(fn):
            R.append((method, re.compile("^" + pattern + "$"), key, fn))
            return fn
        return deco

    @r("GET", "/api/health")
    def health(h, m, q, b, p):
        from nyayavedika import llm
        return {"llm_enabled": llm.available(), "server": "dev_api (stdlib)", "database": config.DATABASE_URL.split(":")[0]}

    @r("GET", "/api/whoami", "GET /api/whoami")
    def whoami(h, m, q, b, p):
        return {"role": p.role, "actor": p.actor, "demo_mode": config.DEMO_MODE}

    @r("GET", "/api/today", "GET /api/today")
    def today(h, m, q, b, p):
        return _court(cause_list.today_counters)

    @r("GET", "/api/intake/limits", "GET /api/intake/limits")
    def limits(h, m, q, b, p):
        return intake.limits()

    @r("POST", "/api/intake/batches", "POST /api/intake/batches")
    def create(h, m, q, b, p):
        f, files = _multipart(h, b)
        real = [x for x in files if not intake.is_junk(x[0] or "")]
        if len(real) > config.DEMO_MAX_FILES:
            raise HttpError(400, f"Demo mode: up to {config.DEMO_MAX_FILES} files at a time. This batch has {len(real)} files.")
        g = lambda k: (f.get(k) or [None])[0]  # noqa: E731
        return _intake(intake.create_batch, files, g("mode") or "separate", g("case_number"), f.get("relative_paths"),
                       g("text"), p.actor)

    @r("GET", r"/api/intake/batches/(?P<id>[^/]+)", "GET /api/intake/batches/{batch_id}")
    def status(h, m, q, b, p):
        return _intake(intake.batch_status, m["id"])

    @r("POST", r"/api/intake/batches/(?P<id>[^/]+)/jobs/(?P<job>[^/]+)/retry", "POST /api/intake/batches/{batch_id}/jobs/{job_id}/retry")
    def retry(h, m, q, b, p):
        return _intake(intake.retry_job, m["id"], m["job"])

    @r("GET", "/api/docket", "GET /api/docket")
    def docket(h, m, q, b, p):
        t = lambda k: (q.get(k) or [""])[0] == "true"  # noqa: E731
        s = lambda k: (q.get(k) or [""])[0]  # noqa: E731
        return _court(staff_api.docket, s("band"), s("case_type"), s("flag"), t("deferred3"), t("needs_review"), t("custody"),
                      t("past_deadline"), s("q"), 200, t("not_listed"))

    @r("GET", r"/api/cases/(?P<id>.+)/detail", "GET /api/cases/{case_id:path}/detail")
    def detail(h, m, q, b, p):
        out = _court(staff_api.case_detail, m["id"])
        if out is None:
            raise HttpError(404, f"No case {m['id']}")
        return out

    @r("PATCH", r"/api/cases/(?P<id>.+)", "PATCH /api/cases/{case_id:path}")
    def patch(h, m, q, b, p):
        return _intake(intake.patch_case, m["id"], json.loads(b or b"{}"), p.actor, p.role)

    @r("POST", r"/api/cases/(?P<id>.+)/accept-slot", "POST /api/cases/{case_id:path}/accept-slot")
    def accept(h, m, q, b, p):
        d = json.loads(b or b"{}")
        return _court(cause_list.accept_slot, m["id"], d.get("action"), p.actor, p.role, d.get("day"), d.get("bench_id"), d.get("hold_until"),
                      d.get("cause_list_id"))

    @r("GET", r"/api/documents/(?P<doc>[^/]+)/pages/(?P<n>\d+)", "GET /api/documents/{doc_id}/pages/{page}")
    def page(h, m, q, b, p):
        if db.is_advocate_document(m["doc"]):
            raise HttpError(404, "No such document")
        out = _court(staff_api.source_page, m["doc"], int(m["n"]))
        if out is None:
            raise HttpError(404, "No such document")
        return out

    @r("POST", "/api/cause-lists/draft", "POST /api/cause-lists/draft")
    def draft(h, m, q, b, p):
        d = json.loads(b or b"{}")
        start = date.fromisoformat(d["start_date"]) if d.get("start_date") else date.today()

        def run(s):
            plan = cause_list.prepare(s, start, int(d.get("days") or 5))
            cid = cause_list.save_draft(s, plan, "DEMO-DC", f"Draft prepared by {p.actor}")
            listed = {c["case_id"] for day in plan["calendar"] for bench in day["benches"] for c in bench["cases"]}
            return {"cause_list_id": cid, "status": "draft", "start_date": plan["start_date"],
                    "already_listed": plan.get("already_listed", [])[:200], "readiness": staff_api.readiness(s, listed),
                    **{k: plan[k] for k in ("metrics", "violations", "capacity_shortfall",
                                            "deadline_alerts", "unscheduled", "calendar")}}
        return _court(run)

    @r("GET", "/api/cause-lists", "GET /api/cause-lists")
    def recent_lists(h, m, q, b, p):
        return _court(cause_list.recent, int((q.get("limit") or [12])[0]))

    @r("GET", r"/api/cause-lists/(?P<id>\d+)/view", "GET /api/cause-lists/{cause_list_id}/view")
    def view_list(h, m, q, b, p):
        return _court(cause_list.view, int(m["id"]))

    @r("GET", "/api/scheduling/preview", "GET /api/scheduling/preview")
    def scheduling_preview(h, m, q, b, p):
        try:
            start = date.fromisoformat(q["start"][0]) if q.get("start") else date.today()
        except ValueError:
            raise HttpError(400, "start must be a date in YYYY-MM-DD form")
        return _court(cause_list.preview, start, int((q.get("days") or [5])[0]))

    @r("GET", "/api/hearings", "GET /api/hearings")
    def hearings(h, m, q, b, p):
        try:
            start = date.fromisoformat(q["start"][0]) if q.get("start") else date.today()
        except ValueError:
            raise HttpError(400, "start must be a date in YYYY-MM-DD form")
        return _court(staff_api.hearing_board, start, int((q.get("days") or [1])[0]))

    @r("POST", r"/api/hearings/(?P<id>\d+)/outcome", "POST /api/hearings/{hearing_id}/outcome")
    def hearing_outcome(h, m, q, b, p):
        d = json.loads(b or b"{}")
        return _court(cause_list.record_outcome, int(m["id"]), d.get("outcome", ""), p.actor, p.role,
                      d.get("reason"), d.get("next_date"))

    @r("GET", r"/api/cause-lists/(?P<id>\d+)", "GET /api/cause-lists/{cause_list_id}")
    def get_list(h, m, q, b, p):
        return _db(lambda s: {**s.select("cause_lists", {"id": int(m["id"])})[0],
                              "listings": s.select("listings", {"cause_list_id": int(m["id"])})})

    @r("POST", r"/api/cause-lists/(?P<id>\d+)/publish", "POST /api/cause-lists/{cause_list_id}/publish")
    def publish(h, m, q, b, p):
        return _court(cause_list.publish, int(m["id"]), p.actor, p.role)

    @r("POST", r"/api/cause-lists/(?P<id>\d+)/reject", "POST /api/cause-lists/{cause_list_id}/reject")
    def reject(h, m, q, b, p):
        return _court(cause_list.reject, int(m["id"]), p.actor, p.role, json.loads(b or b"{}").get("note", ""))

    @r("GET", "/api/alerts", "GET /api/alerts")
    def alerts(h, m, q, b, p):
        result = _db(staff_api.alerts, (q.get("status") or ["pending"])[0])
        if p.role == auth.LAWYER:
            result["alerts"] = [a for a in result["alerts"] if undertrial_watch.has_counsel_on_record(a)]
        return result

    @r("GET", "/api/alerts/data-needed", "GET /api/alerts/data-needed")
    def needed(h, m, q, b, p):
        return {"data_needed": undertrial_watch.scan_candidates()["data_needed"]}

    @r("POST", "/api/alerts/decide", "POST /api/alerts/decide")
    def decide(h, m, q, b, p):
        d = json.loads(b or b"{}").get("decisions") or {}
        if any(not v.get("approve") and not (v.get("reason") or v.get("note")) for v in d.values()):
            raise HttpError(400, "Dismissing needs a reason")
        try:
            return {"decisions_applied": undertrial_watch.decide_alerts(d, p.actor, p.role)}
        except PermissionError as exc:
            raise HttpError(403, str(exc))
        except (ValueError, LookupError) as exc:
            raise HttpError(400, str(exc))

    @r("POST", r"/api/alerts/(?P<id>\d+)/counsel", "POST /api/alerts/{alert_id}/counsel")
    def counsel(h, m, q, b, p):
        d = json.loads(b or b"{}")
        try:
            return undertrial_watch.assign_counsel(int(m["id"]), d.get("name", ""), d.get("basis", ""),
                                                   d.get("reference", ""), p.actor, p.role)
        except LookupError as exc:
            raise HttpError(404, str(exc))
        except ValueError as exc:
            raise HttpError(400, str(exc))

    @r("POST", r"/api/alerts/(?P<id>\d+)/state", "POST /api/alerts/{alert_id}/state")
    def state(h, m, q, b, p):
        d = json.loads(b or b"{}")
        try:
            return undertrial_watch.advance_alert(int(m["id"]), d.get("status"), p.actor, p.role, d.get("note"), d.get("reason"),
                                                  d.get("snooze_until"))
        except PermissionError as exc:
            raise HttpError(403, str(exc))
        except LookupError as exc:
            raise HttpError(404, str(exc))
        except ValueError as exc:
            raise HttpError(400, str(exc))

    @r("GET", r"/api/alerts/(?P<id>\d+)/release\.docx", "GET /api/alerts/{alert_id}/release.docx")
    def release(h, m, q, b, p):
        rows = _db(lambda s: s.select("alerts", {"id": int(m["id"])}))
        if not rows:
            raise HttpError(404, "No alert")
        if p.role == auth.LAWYER and not undertrial_watch.has_counsel_on_record(rows[0]):
            raise HttpError(403, "The court registry must record counsel on the alert before counsel can access it.")
        return legal_aid_docx.build_release_docx(rows[0]), DOCX, _docx_name("release_application", rows[0]["case_id"])

    @r("GET", r"/api/alerts/(?P<id>\d+)/superintendent\.docx", "GET /api/alerts/{alert_id}/superintendent.docx")
    def superintendent(h, m, q, b, p):
        rows = _db(lambda s: s.select("alerts", {"id": int(m["id"])}))
        if not rows:
            raise HttpError(404, "No alert")
        language = (q.get("language") or ["en"])[0]
        if language not in ("en", "hi", "te"):
            raise HttpError(400, "language must be 'en', 'hi' or 'te'")
        alert = rows[0]
        if alert.get("kind") not in ("undertrial_release", "release_review_request"):
            raise HttpError(409, "This alert is not a Section 479 release review.")
        case = store.get_case(alert.get("case_id") or "")
        data = {**(case or {}), **alert}
        name = f"custody_record_review_request_{language}"
        return legal_aid_docx.build_superintendent_docx(data, language), DOCX, _docx_name(name, alert["case_id"])

    @r("POST", r"/api/jobs/(?P<name>\w+)/run", "POST /api/jobs/{name}/run")
    def job(h, m, q, b, p):
        try:
            return jobs.run(m["name"])
        except KeyError as exc:
            raise HttpError(404, str(exc))

    @r("GET", "/api/rules", "GET /api/rules")
    def rules_explained(h, m, q, b, p):
        return staff_api.rules()

    @r("GET", "/api/insights/weekly", "GET /api/insights/weekly")
    def weekly(h, m, q, b, p):
        return _db(staff_api.weekly)

    @r("GET", "/api/impact", "GET /api/impact")
    def impact_summary(h, m, q, b, p):
        try:
            from nyayavedika import impact
            return impact.summary()
        except Exception:  # impact events need SQLAlchemy; show zeros rather than fail the page
            zero = {"people_reached": 0, "legal_aid": {"eligibility_checks": 0, "found_eligible": 0}, "documents": {"analyzed": 0, "pages": 0},
                    "undertrials": {"flagged": 0, "release_applications_approved": 0}, "registry": {"cause_lists_published": 0, "cases_listed": 0}}
            return {**zero, "note": "impact log unavailable on dev_api (needs SQLAlchemy)"}

    @r("GET", "/api/demo/metrics")
    def demo_metrics(h, m, q, b, p):
        return impact.demo_summary()

    @r("POST", r"/api/reach/(?P<door>public|citizen|advocate|staff)")
    def record_reach(h, m, q, b, p):
        try:
            body = json.loads(b or b"{}")
            visitor_hash = impact.reach_hash(body.get("browser_id", ""))
        except (json.JSONDecodeError, ValueError, AttributeError) as exc:
            raise HttpError(400, "browser_id must be a UUID v4") from exc
        db.register_reach(visitor_hash, m["door"])
        return {"ok": True}

    def _report(fn, *a):
        try:
            return _db(fn, *a)
        except impact_reports.ReportError as exc:
            raise HttpError(exc.status, exc.message)

    @r("GET", "/api/impact-reports/options")
    def impact_report_options(h, m, q, b, p):
        return impact_reports.options()

    @r("POST", "/api/impact-reports")
    def impact_report_submit(h, m, q, b, p):
        if not impact_reports.rate_ok(h.client_address[0] if h.client_address else ""):
            raise HttpError(429, "Too many reports from this connection. Please try again in an hour.")
        try:
            body = json.loads(b or b"{}")
        except json.JSONDecodeError:
            raise HttpError(400, "Send the report as JSON")
        return _report(impact_reports.submit, body if isinstance(body, dict) else {})

    @r("GET", "/api/impact-reports", "GET /api/impact-reports")
    def impact_report_list(h, m, q, b, p):
        return _report(impact_reports.listing, (q.get("status") or [""])[0])

    @r("GET", "/api/impact-reports/summary", "GET /api/impact-reports/summary")
    def impact_report_summary(h, m, q, b, p):
        return _report(impact_reports.summary)

    @r("GET", r"/api/impact-reports/export\.csv", "GET /api/impact-reports/export.csv")
    def impact_report_export(h, m, q, b, p):
        return _report(impact_reports.export_csv).encode("utf-8"), "text/csv", f"impact_reports_{date.today().isoformat()}.csv"

    @r("POST", r"/api/impact-reports/(?P<id>\d+)/verify", "POST /api/impact-reports/{report_id}/verify")
    def impact_report_verify(h, m, q, b, p):
        d = json.loads(b or b"{}")
        return _report(impact_reports.verify, int(m["id"]), d.get("status", ""), p.actor, d.get("note", ""))

    @r("GET", r"/api/impact/export\.csv", "GET /api/impact/export.csv")
    def csv(h, m, q, b, p):
        return b"id,timestamp_utc,event,value,meta\n", "text/csv", "impact.csv"

    @r("GET", "/api/field-feedback", "GET /api/field-feedback")
    def field_feedback_wall(h, m, q, b, p):
        return _db(feedback.public)

    @r("GET", "/api/field-feedback/all", "GET /api/field-feedback/all")
    def field_feedback_all(h, m, q, b, p):
        return _db(feedback.public, limit=None)

    @r("POST", "/api/field-feedback", "POST /api/field-feedback")
    def field_feedback_submit(h, m, q, b, p):
        try:
            d = json.loads(b or b"{}")
            out = _db(feedback.submit, d, p.role)
        except json.JSONDecodeError:
            raise HttpError(400, "Send JSON")
        except feedback.FeedbackError as exc:
            raise HttpError(exc.status, exc.message)
        impact.record("feedback", float(d.get("rating") or 0), feature="landing", role=str(d.get("role") or ""))
        return out

    @r("POST", r"/api/field-feedback/(?P<feedback_id>\d+)/hide", "POST /api/field-feedback/{feedback_id}/hide")
    def field_feedback_hide(h, m, q, b, p):
        try:
            out = _db(feedback.hide, int(m["feedback_id"]))
        except feedback.FeedbackError as exc:
            raise HttpError(exc.status, exc.message)
        store.audit(p.actor, p.role, "field_feedback_hide", f"field_feedback:{m['feedback_id']}")
        return out

    @r("POST", "/api/legal-aid", "POST /api/legal-aid")
    def la(h, m, q, b, p):
        d = json.loads(b or b"{}")
        applicant = {**(d.get("applicant") or {}), **({"district": d["district"]} if d.get("district") else {}),
                     **({"state": d["state"]} if d.get("state") else {})}
        out = legal_aid.check_eligibility(applicant)
        out["request_id"] = _db(lambda s: s.insert("legal_aid_requests", [{
            "channel": "web", "district": d.get("district") or None, "state": out["state"], "language": d.get("language"),
            "eligible": out["eligible"], "grounds": [g["clause"] for g in out["grounds"]], "status": "checked", "source": "web",
            "created_at": datetime.now(timezone.utc)}], returning="id"))
        if d.get("draft"):
            out["draft"] = legal_aid.draft_application(applicant, out, d.get("problem") or "", d.get("language") or "English")
        return out

    @r("POST", "/api/legal-aid/explain", "POST /api/legal-aid/explain")
    def la_explain(h, m, q, b, p):
        d = json.loads(b or b"{}")
        applicant = {**(d.get("applicant") or {}), **({"district": d["district"]} if d.get("district") else {}),
                     **({"state": d["state"]} if d.get("state") else {})}
        return legal_aid.explain(legal_aid.check_eligibility(applicant), d.get("problem") or "", d.get("language") or "English")

    @r("POST", "/api/legal-problem/research", "POST /api/legal-problem/research")
    def legal_problem_research(h, m, q, b, p):
        d = json.loads(b or b"{}")
        try:
            return legal_problem.research(d.get("description") or "", d.get("language") or "English",
                                          d.get("jurisdiction") or "")
        except legal_problem.ResearchUnavailable as exc:
            raise HttpError(503, str(exc))
        except legal_problem.InvalidResearchOutput as exc:
            raise HttpError(502, str(exc))
        except ValueError as exc:
            raise HttpError(400, str(exc))
        except Exception as exc:
            import logging
            logging.getLogger("nyayavedika.dev_api").exception(
                "Citizen legal-problem research failed: %s", type(exc).__name__)
            raise HttpError(502, "Legal research could not be completed. No answer was generated; please try again.")

    @r("POST", "/api/advocate/workspaces", "POST /api/advocate/workspaces")
    def advocate_workspace(h, m, q, b, p):
        return advocate.create_workspace()

    @r("POST", "/api/advocate/documents", "POST /api/advocate/documents")
    def advocate_upload(h, m, q, b, p):
        d = json.loads(b or b"{}")
        try:
            data = base64.b64decode(d.get("content_base64") or "", validate=True)
        except (ValueError, binascii.Error):
            raise HttpError(400, "The uploaded file is not valid base64")
        try:
            return advocate.upload_document(d.get("workspace_token") or "", d.get("filename") or "", data)
        except advocate.AdvocateError as exc:
            raise HttpError(exc.status, str(exc))

    @r("POST", r"/api/advocate/documents/(?P<doc>[^/]+)/insights",
       "POST /api/advocate/documents/{doc_id}/insights")
    def advocate_insight(h, m, q, b, p):
        d = json.loads(b or b"{}")
        try:
            return advocate.generate_insight(
                d.get("workspace_token") or "", m["doc"], d.get("insight_type") or "", d.get("user_guidance")
            )
        except advocate.AdvocateError as exc:
            raise HttpError(exc.status, str(exc))

    @r("POST", "/api/advocate/studio", "POST /api/advocate/studio")
    def advocate_studio(h, m, q, b, p):
        d = json.loads(b or b"{}")
        try:
            return document_studio.process(d.get("operation") or "", d.get("files") or [], d.get("options") or {})
        except document_studio.StudioError as exc:
            raise HttpError(exc.status, str(exc))

    @r("POST", "/api/legal-aid/ask", "POST /api/legal-aid/ask")
    def la_ask(h, m, q, b, p):
        d = json.loads(b or b"{}")
        question = (d.get("question") or "").strip()
        if not question:
            raise HttpError(400, "Enter a question")
        if len(question) > 1500:
            raise HttpError(413, "Question is too long (1500 character limit)")
        session_id = d.get("question_session") or ""
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", session_id):
            raise HttpError(400, "Start a new legal-aid session and try again.")
        attachments = d.get("documents") or []
        if len(attachments) > legal_aid.MAX_QUESTION_DOCUMENTS:
            raise HttpError(413, f"Attach no more than {legal_aid.MAX_QUESTION_DOCUMENTS} documents per question.")
        if legal_aid.followups_used(session_id) >= legal_aid.MAX_FOLLOWUPS:
            raise HttpError(429, f"This session has reached its {legal_aid.MAX_FOLLOWUPS}-question follow-up limit. "
                                 "Start a new legal-aid session to continue.")
        text_parts, names, total_size = [], [], 0
        for doc in attachments:
            filename, pages, size = _document_pages(doc)
            total_size += size
            if total_size > config.MAX_UPLOAD_BYTES:
                raise HttpError(413, "Combined documents exceed the upload limit")
            names.append(filename)
            text_parts.extend(f"[{filename}, page {page['page']}]\n{page['text']}" for page in pages
                              if (page.get("text") or "").strip())
        document_text = "\n\n".join(text_parts)
        if len(document_text) > 20000:
            raise HttpError(413, "Attached documents contain too much text for one question (20,000 character limit)")
        answer = legal_aid.answer_question(question, d.get("language") or "English", document_text,
                                           ", ".join(names) or "Uploaded document")
        try:
            answer["followups_used"] = legal_aid.record_followup(session_id)
        except legal_aid.FollowupLimitReached as exc:
            raise HttpError(429, str(exc))
        answer["followups_limit"] = legal_aid.MAX_FOLLOWUPS
        return answer

    @r("POST", "/api/documents/summarize", "POST /api/documents/summarize")
    def summarize_document(h, m, q, b, p):
        d = json.loads(b or b"{}")
        filename, pages, _ = _document_pages(d)
        return {"filename": filename, "pages": len(pages),
                **summarise.summarise_pages(pages, language=d.get("language") or "English")}

    @r("POST", r"/api/legal-aid/application\.docx", "POST /api/legal-aid/application.docx")
    def la_docx(h, m, q, b, p):
        d = json.loads(b or b"{}")
        data = legal_aid_docx.build_application_docx({"applicant": d.get("applicant") or {}, "problem": d.get("problem") or "",
                                                      "district": d.get("district"), "state": d.get("state")})
        return data, DOCX, _docx_name("legal_aid_application", d.get("district"))

    @r("GET", "/api/legal-aid/topics", "GET /api/legal-aid/topics")
    def kb_topics(h, m, q, b, p):
        return legal_aid_kb.topics()

    @r("GET", "/api/legal-aid/kb", "GET /api/legal-aid/kb")
    def kb(h, m, q, b, p):
        return legal_aid_kb.search((q.get("q") or [""])[0], int((q.get("top_k") or ["4"])[0]))

    @r("POST", "/api/agent/chat", "POST /api/agent/chat")
    def chat(h, m, q, b, p):
        d = json.loads(b or b"{}")
        return _chat(p, d.get("message", ""), d.get("thread_id"))

    @r("POST", "/api/agent/chat/files", "POST /api/agent/chat/files")
    def chat_files(h, m, q, b, p):
        f, files = _multipart(h, b)
        real = [x for x in files if not intake.is_junk(x[0] or "")]
        if len(real) > config.DEMO_MAX_FILES:
            raise HttpError(400, f"Up to {config.DEMO_MAX_FILES} files at a time. This message has {len(real)} files.")
        batch = _intake(intake.create_batch, files, "separate" if p.role == "staff" else "summary_only", None,
                        f.get("relative_paths"), None, p.actor)
        g = lambda k: (f.get(k) or [""])[0]  # noqa: E731
        return {**_chat(p, g("message") or "What does this document say?", g("thread_id") or None, batch["batch_id"]),
                "files": batch["files"]}

    return R


ROUTES = routes()
PAGES = {"/": "index.html", "/staff": "staff.html", "/advocate": "advocate.html",
         "/citizen": "citizen.html", "/feedback": "feedback-wall.html", "/metrics": "metrics.html",
         "/impact-report": "impact-report.html", "/impact-report/review": "impact-review.html"}
DOWNLOADS = {"/pilot/template.csv": ROOT / "pilot" / "pilot_log_template.csv"}
DOCS = {"/how-it-works": "how-it-works", "/research-evidence": "research-evidence"}
TYPES = {".html": "text/html; charset=utf-8", ".js": "text/javascript; charset=utf-8", ".css": "text/css; charset=utf-8",
         ".json": "application/json; charset=utf-8", ".svg": "image/svg+xml", ".png": "image/png"}


class Handler(BaseHTTPRequestHandler):
    server_version = "nyayavedika-dev-api"

    def log_message(self, fmt, *args):  # quiet; errors still print
        pass

    def _send(self, status, body: bytes, ctype: str, extra=None):
        self.send_response(status)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        for k, v in (extra or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    def _json(self, status, obj):
        self._send(status, json.dumps(obj, default=str, ensure_ascii=False).encode(), "application/json")

    def _record_api_activity(self, method, path, key, status, started, principal):
        route_path = key.split(" ", 1)[1] if key else path
        feature = impact.api_feature(route_path, method)
        if not feature:
            return
        door = {"citizen": "citizen", "lawyer": "advocate", "staff": "staff"}.get(
            getattr(principal, "role", "")
        ) or impact.api_door(
            route_path, method, self.headers.get("Authorization"), self.headers.get("X-Demo-Role")
        )
        feature = impact.api_feature(route_path, method, door)
        impact.record_api_usage(door, feature, method, status, (time.perf_counter() - started) * 1000)
        browser_id = self.headers.get("X-Anonymous-Browser-ID", "")
        if browser_id:
            impact.record_browser_activity(browser_id, door, feature)

    def _handle(self, method):
        url = urlparse(self.path)
        path = url.path
        if method == "GET" and path in DOCS:
            return self._send(200, public_docs.render_page(DOCS[path]).encode("utf-8"), TYPES[".html"])
        if method == "GET" and path in DOWNLOADS:
            return self._send(200, DOWNLOADS[path].read_bytes(), "text/csv; charset=utf-8",
                              {"Content-Disposition": 'attachment; filename="pilot_log_template.csv"'})
        if method == "GET" and (path in PAGES or path.startswith("/static/")):
            f = STATIC / (PAGES.get(path) or path[len("/static/"):])
            if f.resolve().is_file() and STATIC.resolve() in f.resolve().parents:
                if method == "GET" and path in ("/citizen", "/advocate", "/staff"):
                    impact.record_door_visit(path.lstrip("/"))
                return self._send(200, f.read_bytes(), TYPES.get(f.suffix, "application/octet-stream"))
            return self._json(404, {"detail": "Not found"})
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0)) if method in ("POST", "PATCH") else b""
        for m_, rx, key, fn in ROUTES:
            mt = rx.match(path) if m_ == method else None
            if not mt:
                continue
            started = time.perf_counter()
            status = 200
            principal = None
            try:
                principal = _guard(self, key) if key else None
                out = fn(self, mt.groupdict(), parse_qs(url.query), body, principal)
                if isinstance(out, tuple):
                    data, ctype, name = out
                    return self._send(200, data, ctype, {"Content-Disposition": f'attachment; filename="{name}"'})
                return self._json(200, out)
            except HttpError as exc:
                status = exc.status
                return self._json(exc.status, {"detail": exc.detail})
            except Exception as exc:  # pragma: no cover - surfaced to the UI as a toast
                status = 500
                return self._json(500, {"detail": f"{type(exc).__name__}: {exc}"})
            finally:
                if path.startswith("/api/"):
                    self._record_api_activity(method, path, key, status, started, principal)
        self._json(404, {"detail": "Not found"})

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PATCH(self):
        self._handle("PATCH")


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--port", type=int, default=config.DEV_API_PORT)
    ap.add_argument("--host", default=config.DEV_API_HOST)
    ap.add_argument("--no-worker", action="store_true")
    ap.add_argument("--seed", type=int, default=config.DEMO_SEED_CASES, help="seed this many synthetic cases if the docket is empty")
    a = ap.parse_args()
    with store.connect() as s:
        store.prepare_database(s)
        store.load_reference_into_triage(s)
        if a.seed and not s.count("cases"):
            demo_seed.write(s, demo_seed.build(a.seed, 42, date.today()))
    if not a.no_worker:
        threading.Thread(target=worker.run, kwargs={"once": False, "concurrency": 1}, daemon=True).start()
    if not auth.configured_roles():
        print("No DEMO_TOKEN_* set: only the citizen portal (anonymous) will work. Set them in .env or the environment.")
    for problem in auth.token_problems():
        print("WARNING access tokens:", problem)
    print(f"NyayaVedika dev API on http://{a.host}:{a.port}  (staff: /staff, citizen: /citizen)")
    ThreadingHTTPServer((a.host, a.port), Handler).serve_forever()


if __name__ == "__main__":
    main()
