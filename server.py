"""NyayaVedika API - FastAPI + LangGraph agents.

    uvicorn server:app --host 127.0.0.1 --port 8000      (or: python server.py)
"""
import base64
import binascii
import logging
import mimetypes
import os
import re
import threading
import time
import uuid
from contextlib import asynccontextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

ROOT = Path(__file__).parent
# Settings: nyayavedika.config loads .env itself on import (nyayavedika/envfile.py); nothing to do here.

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, PlainTextResponse, Response  # noqa: E402
from fastapi.middleware.gzip import GZipMiddleware  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402
from starlette.concurrency import run_in_threadpool  # noqa: E402
from langgraph.types import Command  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from nyayavedika import (advocate, audit, auth, cause_list, config, db, document_studio, documents, drafting, impact, intake, jobs, legal_problem,  # noqa: E402
                   legal_aid, llm, ocr, sample_data, scheduler, staff_api, store, offline_summary, summarise, triage, vectorstore,
                   websearch, public_docs)
from nyayavedika.agents import assistants, checkpoint, document_analyst, registry, undertrial_watch  # noqa: E402
from nyayavedika.agents.context import clean_context  # noqa: E402
from nyayavedika.agents.front_door import answer_kind  # noqa: E402
from nyayavedika.agents.react import new_turn  # noqa: E402
from nyayavedika import feedback as feedback_mod  # noqa: E402
from nyayavedika import impact_reports  # noqa: E402
from nyayavedika.auth import Principal, guard  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("nyayavedika")
DOCX_TYPE = "application/vnd.openxmlformats-officedocument.wordprocessingml.document"


@asynccontextmanager
async def lifespan(_app):
    _startup()
    try:
        yield
    finally:
        _shutdown()


app = FastAPI(title="NyayaVedika", version="2.0", lifespan=lifespan)
# JSON (docket, cause-list drafts) and the JS/CSS bundles compress ~70-85%; small replies are left alone
app.add_middleware(GZipMiddleware, minimum_size=1024)
_worker_stop = threading.Event()
_worker_thread: Optional[threading.Thread] = None


@app.middleware("http")
async def collect_api_usage(request: Request, call_next):
    started = time.perf_counter()
    status_code = 500
    try:
        response = await call_next(request)
        status_code = response.status_code
        return response
    finally:
        route = request.scope.get("route")
        route_path = getattr(route, "path", "")
        if request.method == "GET" and request.url.path in ("/citizen", "/advocate", "/staff"):
            await run_in_threadpool(impact.record_door_visit, request.url.path.lstrip("/"))
        feature = impact.api_feature(route_path, request.method) if request.url.path.startswith("/api/") else None
        if feature:
            duration_ms = (time.perf_counter() - started) * 1000
            door = impact.api_door(
                route_path, request.method, request.headers.get("authorization"),
                request.headers.get("x-demo-role"),
            )
            feature = impact.api_feature(route_path, request.method, door)
            await run_in_threadpool(
                impact.record_api_usage, door, feature, request.method, status_code, duration_ms
            )
            browser_id = request.headers.get("x-anonymous-browser-id", "")
            if browser_id:
                await run_in_threadpool(impact.record_browser_activity, browser_id, door, feature)


def _start_inline_worker():
    """Run the intake worker inside this process so one command is enough.
    Set NYAYAVEDIKA_INLINE_WORKER=0 to run `python -m nyayavedika.worker` separately instead (jobs are claimed with
    SKIP LOCKED, so running both is also safe)."""
    global _worker_thread
    if not config.INLINE_WORKER:
        return
    from nyayavedika import worker
    _worker_stop.clear()
    _worker_thread = threading.Thread(target=worker.run, kwargs={"concurrency": config.WORKER_CONCURRENCY,
                                                                  "stop": _worker_stop},
                                      name="inline-worker", daemon=True)
    _worker_thread.start()
    logger.info("Intake worker running in-process (concurrency %d)", config.WORKER_CONCURRENCY)


def _startup():
    from nyayavedika import envfile
    src = envfile.loaded_from()
    if src:
        logger.info("Settings read from %s", src)  # the path only, never values
    db.engine()
    checkpoint.get_checkpointer()  # open the Postgres pool now so a bad DSN fails at boot, not mid-conversation
    if not auth.configured_roles():
        logger.warning("No DEMO_TOKEN_STAFF / DEMO_TOKEN_LAWYER / DEMO_TOKEN_CITIZEN set: every /api call except "
                       "/api/health will return 401. Set them in .env.")
    for problem in auth.token_problems():
        logger.warning("Access tokens: %s", problem)
    store.prepare_database()  # idempotent migration + reference rows (scripts/migrate_demo.py does the same)
    if store.load_reference_into_triage():
        logger.info("Triage constants loaded from case_type_ref / stage_ref")
    if not db.list_cases():
        cases = sample_data.generate(config.DEMO_SEED_CASES)
        store.upsert_cases(cases, {r["case_id"]: r for r in triage.triage_all(cases)}, source="synthetic")
        logger.info("Seeded synthetic demo docket (%d cases, labelled synthetic)", config.DEMO_SEED_CASES)
    _start_inline_worker()


def _shutdown():
    _worker_stop.set()
    if _worker_thread is not None:
        _worker_thread.join(timeout=config.SHUTDOWN_JOIN_SECONDS)
    checkpoint.close()


def _interrupt_payload(out: Dict) -> Optional[Any]:
    intr = out.get("__interrupt__")
    if not intr:
        return None
    first = intr[0] if isinstance(intr, (list, tuple)) else intr
    return getattr(first, "value", first)


def _cfg(thread_id: str) -> Dict:
    return {"configurable": {"thread_id": thread_id}}


def _document_pages(body: "DocIn"):
    suffix = Path(body.filename).suffix.lower().lstrip(".")
    if suffix not in config.ALLOWED_EXTS:
        raise HTTPException(400, f"File type .{suffix or '(none)'} is not accepted")
    if body.content_base64:
        try:
            data = base64.b64decode(body.content_base64, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(400, "The uploaded file is not valid base64")
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "File too large")
        pages = ocr.extract(data, body.filename)
        size = len(data)
    elif body.text and body.text.strip():
        data = body.text.encode("utf-8")
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Text is too large")
        pages = [{"page": 1, "text": body.text, "source": "text", "confidence": None}]
        size = len(data)
    else:
        raise HTTPException(400, "Send a file or document text")
    if len(pages) > min(config.DEMO_MAX_PAGES, 50):
        raise HTTPException(413, f"Document exceeds the 50-page-per-file limit")
    if not any((page.get("text") or "").strip() for page in pages):
        raise HTTPException(400, "No readable text found in the document")
    return pages, size


# ----------------------------------------------------------------------------- models
class ChatIn(BaseModel):
    message: str
    thread_id: Optional[str] = None
    language: str = ""
    agent: str = "citizen"     # ignored: the agent comes from the caller's role (token)
    context: Optional[Dict[str, Any]] = None   # the 5-question guide's answers + result, so the chat continues from it


class ResumeIn(BaseModel):
    thread_id: str
    answer: Any
    agent: str = "citizen"     # ignored, as above
    language: str = ""


class DocIn(BaseModel):
    filename: str = "document.txt"
    content_base64: Optional[str] = None
    text: Optional[str] = None
    case_id: Optional[str] = None
    language: str = "English"


class RegistryIn(BaseModel):
    court_id: Optional[str] = None
    start_date: Optional[str] = None
    days: int = 5
    benches: Optional[List[dict]] = None


class DecisionIn(BaseModel):
    thread_id: Optional[str] = None
    decisions: Dict[str, dict] = {}     # undertrial: {alert_id: {"approve": bool, "note": str}}
    approve: Optional[bool] = None      # registry
    note: str = ""


class LegalAidIn(BaseModel):
    applicant: Dict[str, Any] = {}
    problem: str = ""
    language: str = "English"
    draft: bool = False
    district: str = ""
    state: str = ""


class LegalProblemResearchIn(BaseModel):
    description: str
    language: str = "English"
    jurisdiction: str = ""


class LegalProblemChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    kind: str = ""


class LegalProblemChatIn(BaseModel):
    messages: List[LegalProblemChatMessageIn]
    language: str = "English"


class AdvocateDocumentIn(BaseModel):
    workspace_token: str
    filename: str
    content_base64: str


class AdvocateInsightIn(BaseModel):
    workspace_token: str
    insight_type: str
    user_guidance: Optional[str] = None


class AdvocateChatMessageIn(BaseModel):
    role: Literal["user", "assistant"]
    content: str


class AdvocateChatIn(BaseModel):
    workspace_token: str
    messages: List[AdvocateChatMessageIn]


class AdvocateChatPrepareIn(BaseModel):
    workspace_token: str


class AdvocateDocumentPreviewIn(BaseModel):
    workspace_token: str


class AdvocateStudioIn(BaseModel):
    operation: str
    files: List[Dict[str, Any]]
    options: Dict[str, Any] = {}


class LegalAidAskIn(BaseModel):
    question: str
    question_session: str
    language: str = "English"
    documents: List[DocIn] = []


class FeedbackIn(BaseModel):
    feature: str
    rating: int
    role: str = "citizen"      # ignored: the role recorded is the caller's (token)
    comment: str = ""


class ReachIn(BaseModel):
    browser_id: str


# ----------------------------------------------------------------------------- health
@app.get("/api/health")
def health():
    return {**llm.status(), "vector": vectorstore.status(), "web_search": websearch.available(),
            "ocr": ocr.capabilities(), "database": config.DATABASE_URL.split("://")[0],
            "checkpointer": config.CHECKPOINTER, "cases_loaded": _case_count()}


def _case_count() -> int:
    """COUNT(*) instead of loading every case's JSON (the citizen page calls /api/health on every load)."""
    try:
        with store.connect() as s:
            return s.count("cases")
    except Exception:   # health must answer even if the table is not there yet
        return len(db.list_cases())


# ----------------------------------------------------------------------------- conversational agents
def _agent(name: str):
    return assistants.agent_for(name)


def _agent_for(principal: Principal) -> str:
    """One front door; the role (citizen / lawyer / staff) comes from the token and picks the tool set."""
    return principal.role


def _own_thread(thread_id: str, agent: str) -> None:
    if not thread_id.startswith(f"{agent}-"):
        raise HTTPException(403, "This conversation belongs to a different role")


def _has_pending_question(graph, thread_id: str) -> bool:
    """True when the thread is paused on a question the agent asked (ask_user): the next message is its answer."""
    try:
        snap = graph.get_state(_cfg(thread_id))
    except Exception:
        return False
    return any(getattr(t, "interrupts", ()) for t in (getattr(snap, "tasks", None) or ()))


def _agent_reply(out: Dict, thread_id: str) -> Dict:
    q = _interrupt_payload(out)
    door_wait = (out.get("door") or {}).get("awaiting")
    kind = answer_kind(out.get("awaiting") or door_wait, interrupted=q is not None)
    return {"thread_id": thread_id, "reply": None if q else out.get("final"),
            "question": q.get("question") if isinstance(q, dict) else None, "steps": out.get("steps", []),
            "actions": [a for a in out.get("actions", []) if isinstance(a, dict)],
            "answer_kind": kind,                               # confirm | yes_no | text | null: what the screen should offer
            "awaiting_confirmation": kind == "confirm",
            "awaiting_answer": kind is not None}


def _chat(body: "ChatIn", principal: Principal, batch_id: Optional[str] = None) -> Dict:
    role = _agent_for(principal)
    thread_id = body.thread_id or f"{role}-{uuid.uuid4().hex[:12]}"
    _own_thread(thread_id, role)
    if not body.thread_id:  # one session per conversation, counted once (not per message)
        impact.record("citizen_session" if role == "citizen" else "assistant_session", role=role, channel="chat",
                      engine="llm" if llm.available() else "offline")
    graph = _agent(role)
    ctx = clean_context(body.context)   # bounded, plain types only: the browser is not trusted with the prompt
    try:
        if body.thread_id and not batch_id and _has_pending_question(graph, thread_id):
            state_update = {}
            if ctx:   # a fresh guide result while a question is pending: store it, then answer the question
                state_update["context"] = ctx
            if body.language:
                state_update["language"] = body.language
            if state_update:
                graph.update_state(_cfg(thread_id), state_update)
            out = graph.invoke(Command(resume=body.message), _cfg(thread_id))   # the person is answering the agent's question
        else:
            out = graph.invoke(new_turn(body.message, body.language, batch_id, ctx), _cfg(thread_id))
    except Exception as exc:  # a tool or the conversation store failed: the person still gets an answer, never a 500
        logger.exception("chat turn failed on thread %s: %s", thread_id, type(exc).__name__)
        from nyayavedika.agents.front_door import FrontDoor
        door = FrontDoor(role).handle(body.message, None, batch_id, ctx)
        return {"thread_id": thread_id, "reply": "(Something went wrong with the AI assistant, so the built-in guide "
                "answered.)\n\n" + door["reply"], "question": None, "steps": [],
                "actions": [a for a in door.get("actions", []) if isinstance(a, dict)],
                "answer_kind": None, "awaiting_confirmation": False, "awaiting_answer": False}
    return _agent_reply(out, thread_id)


@app.post("/api/agent/chat")
def agent_chat(body: ChatIn, principal: Principal = guard("POST /api/agent/chat")):
    return _chat(body, principal)


@app.post("/api/agent/chat/files")
def agent_chat_files(message: str = Form(""), thread_id: Optional[str] = Form(None), language: str = Form(""),
                     context: str = Form(""), files: List[UploadFile] = File(default=[]), relative_paths: List[str] = Form(default=[]),
                     principal: Principal = guard("POST /api/agent/chat/files")):
    """Attach button: up to DEMO_MAX_FILES files, same validation as intake. Only staff files create cases;
    citizens and lawyers get a summary and nothing is added to the docket."""
    real = [f for f in files if not intake.is_junk(f.filename or "")]
    if len(real) > config.DEMO_MAX_FILES:
        raise HTTPException(400, f"Up to {config.DEMO_MAX_FILES} files at a time. This message has {len(real)} files.")
    cap = config.DEMO_MAX_FILE_MB * 1024 * 1024 + 1
    payload = [(f.filename or "file", f.file.read(cap)) for f in files]
    mode = "separate" if principal.role == auth.STAFF else "summary_only"
    batch = _intake_call(intake.create_batch, payload, mode, None, relative_paths, None, principal.actor)
    body = ChatIn(message=message or "What does this document say?", thread_id=thread_id, language=language,
                  context=clean_context(context))
    return {**_chat(body, principal, batch["batch_id"]), "files": batch["files"]}


@app.post("/api/agent/resume")
def agent_resume(body: ResumeIn, principal: Principal = guard("POST /api/agent/resume")):
    """Answer the agent's question. When the thread is not waiting for one, the answer is simply the next message."""
    role = _agent_for(principal)
    _own_thread(body.thread_id, role)
    graph = _agent(role)
    if not _has_pending_question(graph, body.thread_id):
        return _chat(ChatIn(message=str(body.answer), thread_id=body.thread_id, language=body.language), principal)
    if body.language:
        graph.update_state(_cfg(body.thread_id), {"language": body.language})
    out = graph.invoke(Command(resume=body.answer), _cfg(body.thread_id))
    return _agent_reply(out, body.thread_id)


# ----------------------------------------------------------------------------- document analyst
@app.post("/api/documents/analyze", dependencies=[guard("POST /api/documents/analyze")])
def analyze_document(body: DocIn):
    if body.content_base64:
        try:
            data = base64.b64decode(body.content_base64, validate=True)
        except (ValueError, binascii.Error):
            raise HTTPException(400, "The uploaded file is not valid base64")
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, f"File exceeds the {config.DEMO_MAX_FILE_MB} MB limit")
        suffix = Path(body.filename).suffix.lower().lstrip(".")
        if suffix not in config.ALLOWED_EXTS:
            raise HTTPException(400, f"File type .{suffix or '(none)'} is not accepted")
        if suffix == "pdf":
            pages = intake.pdf_page_count(data)
            if pages and pages > min(config.DEMO_MAX_PAGES, 50):
                raise HTTPException(413, "Document exceeds the 50-page-per-file limit")
        doc_id = documents.generate_file_id(data)
        return document_analyst.analyze(doc_id, body.filename, data=data, case_id=body.case_id, language=body.language)
    if not (body.text or "").strip():
        raise HTTPException(400, "Send a file or text")
    suffix = Path(body.filename).suffix.lower().lstrip(".")
    if suffix not in config.ALLOWED_EXTS:
        raise HTTPException(400, f"File type .{suffix or '(none)'} is not accepted")
    data = body.text.encode("utf-8")
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(413, f"Text exceeds the {config.DEMO_MAX_FILE_MB} MB limit")
    doc_id = documents.generate_file_id(data)
    return document_analyst.analyze(doc_id, body.filename, text=body.text, case_id=body.case_id, language=body.language)


@app.post("/api/documents/summarize", dependencies=[guard("POST /api/documents/summarize")])
def summarize_document(body: DocIn):
    """Summarize an uploaded/pasted document without saving it to a case or the document database."""
    pages, _ = _document_pages(body)
    summary = summarise.summarise_pages(pages, language=body.language or "English", audience="citizen")
    return {"filename": body.filename, "pages": len(pages), **summary}


@app.get("/api/sample-judgment", dependencies=[guard("GET /api/sample-judgment")])
def sample_judgment():
    return {"text": (ROOT / "data" / "sample_judgment.txt").read_text(encoding="utf-8")}


# ----------------------------------------------------------------------------- undertrial watch
@app.post("/api/undertrial/scan", dependencies=[guard("POST /api/undertrial/scan")])
def undertrial_scan(court_id: Optional[str] = None):
    thread_id = f"watch-{uuid.uuid4().hex[:12]}"
    out = undertrial_watch.graph().invoke({"court_id": court_id, "drafts": []}, _cfg(thread_id))
    return {"thread_id": thread_id, "awaiting_approval": _interrupt_payload(out) is not None, "summary": out.get("summary")}


@app.get("/api/alerts")
def list_alerts(status: str = "pending", principal: Principal = guard("GET /api/alerts")):
    """Undertrial cards, sorted by days over the legal limit ('all' for every status)."""
    with store.connect() as s:
        result = staff_api.alerts(s, status)
    if principal.role == auth.LAWYER:
        result["alerts"] = [a for a in result["alerts"] if undertrial_watch.has_counsel_on_record(a)]
    return result


@app.post("/api/alerts/decide")
def decide_alerts(body: DecisionIn, principal: Principal = guard("POST /api/alerts/decide")):
    """{alert_id: {"approve": bool, "note", "reason" (required to dismiss), "snooze_until"}}"""
    missing = [a for a, d in body.decisions.items() if not d.get("approve") and not (d.get("reason") or d.get("note"))]
    if missing:
        raise HTTPException(400, f"Dismissing needs a reason (alerts {', '.join(missing)})")
    if body.thread_id:  # resume the paused watch run
        if not body.thread_id.startswith("watch-") or not _has_pending_question(undertrial_watch.graph(), body.thread_id):
            raise HTTPException(409, "This scan is not waiting for a decision (already decided, or unknown thread)")
        try:
            undertrial_watch.require_counsel_for_decisions(body.decisions, principal.role)
        except PermissionError as exc:
            raise HTTPException(403, str(exc))
        except LookupError as exc:
            raise HTTPException(404, str(exc))
        for alert_id, d in body.decisions.items():
            audit.record(principal, "release_alert_approved" if d.get("approve") else "release_alert_dismissed",
                         f"alert:{alert_id}", thread_id=body.thread_id)
        out = undertrial_watch.graph().invoke(Command(resume=body.decisions), _cfg(body.thread_id))
        return {"summary": out.get("summary")}
    try:
        return {"decisions_applied": undertrial_watch.decide_alerts(body.decisions, principal.actor, principal.role)}
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except (ValueError, LookupError) as exc:
        raise HTTPException(400, str(exc))


class AlertStateIn(BaseModel):
    status: str                      # approved | filed | heard | released | denied | dismissed
    note: str = ""
    reason: str = ""                 # required for dismissed
    snooze_until: Optional[str] = None


@app.post("/api/alerts/{alert_id}/state")
def alert_state(alert_id: int, body: AlertStateIn, principal: Principal = guard("POST /api/alerts/{alert_id}/state")):
    """Advance an alert: pending -> approved -> filed -> heard -> released | denied, or dismissed with a reason."""
    try:
        return undertrial_watch.advance_alert(alert_id, body.status, principal.actor, principal.role, body.note or None,
                                              body.reason or None, body.snooze_until)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except (legal_problem.InvalidResearchInput, ValueError) as exc:   # an impossible step was a 500 before
        raise HTTPException(400, str(exc))


class CounselIn(BaseModel):
    name: str
    basis: str                       # dlsa_assignment | vakalatnama
    reference: str = ""


@app.post("/api/alerts/{alert_id}/counsel")
def alert_counsel(alert_id: int, body: CounselIn, principal: Principal = guard("POST /api/alerts/{alert_id}/counsel")):
    """Court staff record counsel on record (from the DLSA assignment letter or a vakalatnama)."""
    try:
        return undertrial_watch.assign_counsel(alert_id, body.name, body.basis, body.reference, principal.actor,
                                               principal.role)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/alerts/data-needed", dependencies=[guard("GET /api/alerts/data-needed")])
def alerts_data_needed():
    """Custody cases the watch cannot check: missing custody date or sentence, and who can supply it."""
    return {"data_needed": undertrial_watch.scan_candidates()["data_needed"]}


# ----------------------------------------------------------------------------- registry agent
@app.post("/api/registry/run", dependencies=[guard("POST /api/registry/run")])
def registry_run(body: RegistryIn):
    thread_id = f"registry-{uuid.uuid4().hex[:12]}"
    out = registry.graph().invoke({"court_id": body.court_id, "start_date": body.start_date or date.today().isoformat(),
                                   "days": body.days, "benches": body.benches}, _cfg(thread_id))
    return {"thread_id": thread_id, "cause_list_id": out.get("cause_list_id"), "plan": out.get("plan"),
            "review": out.get("review"), "explanation": out.get("explanation"),
            "awaiting_approval": _interrupt_payload(out) is not None,
            "top_cases": [{k: r.get(k) for k in ("case_id", "score", "band", "flags", "reasons", "recommended_route")}
                          | {"case_type": r["case"].get("case_type"), "stage": r["case"].get("stage")}
                          for r in out.get("results", [])[:150]]}


@app.post("/api/registry/decide")
def registry_decide(body: DecisionIn, principal: Principal = guard("POST /api/registry/decide")):
    # publish / reject (with audit_log) happens in the graph's publish step, as this staff user
    if not body.thread_id or not body.thread_id.startswith("registry-"):
        raise HTTPException(400, "Send the thread_id returned by /api/registry/run")
    if not _has_pending_question(registry.graph(), body.thread_id):
        raise HTTPException(409, "This cause list is not waiting for a decision (already decided, or unknown thread)")
    registry.graph().invoke(Command(resume={"approve": bool(body.approve), "note": body.note, "actor": principal.actor,
                                            "role": principal.role}), _cfg(body.thread_id))
    return {"status": "published" if body.approve else "rejected"}


# ----------------------------------------------------------------------------- cause lists with memory (no graph needed)
def _court_call(fn, *args, **kwargs):
    try:
        with store.connect() as s:
            return fn(s, *args, **kwargs)
    except LookupError as exc:
        raise HTTPException(404, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


class DraftIn(BaseModel):
    start_date: Optional[str] = None
    days: int = 5
    court_id: Optional[str] = None


@app.post("/api/cause-lists/draft")
def cause_list_draft(body: DraftIn, principal: Principal = guard("POST /api/cause-lists/draft")):
    """Plan with queue memory, check invariants, save a DRAFT (listings + deferrals). Publishing needs approval."""
    start = date.fromisoformat(body.start_date) if body.start_date else date.today()

    def run(s):
        plan = cause_list.prepare(s, start, body.days, body.court_id)
        cid = cause_list.save_draft(s, plan, body.court_id or "DEMO-DC", f"Draft prepared by {principal.actor}")
        listed = {c["case_id"] for d in plan["calendar"] for b in d["benches"] for c in b["cases"]}
        return {"cause_list_id": cid, "status": "draft", "start_date": plan["start_date"], "metrics": plan["metrics"],
                "violations": plan["violations"],
                "capacity_shortfall": plan["capacity_shortfall"], "deadline_alerts": plan["deadline_alerts"],
                "unscheduled": plan["unscheduled"][:200], "already_listed": plan.get("already_listed", [])[:200],
                "calendar": plan["calendar"], "readiness": staff_api.readiness(s, listed)}
    return _court_call(run)


@app.get("/api/cause-lists", dependencies=[guard("GET /api/cause-lists")])
def cause_lists_recent(limit: int = 12):
    """Recent cause lists (draft, published, rejected, superseded), newest first."""
    return _court_call(cause_list.recent, limit)


@app.get("/api/cause-lists/{cause_list_id}/view", dependencies=[guard("GET /api/cause-lists/{cause_list_id}/view")])
def cause_list_view(cause_list_id: int):
    """A saved list in the draft screen's shape, rebuilt from its current listings (reopen a draft after leaving)."""
    return _court_call(cause_list.view, cause_list_id)


@app.get("/api/scheduling/preview", dependencies=[guard("GET /api/scheduling/preview")])
def scheduling_preview(start: Optional[str] = None, days: int = 5):
    """Before drafting: bench time for the week against the expected time of the cases waiting to be listed."""
    try:
        first = date.fromisoformat(start) if start else date.today()
    except ValueError:
        raise HTTPException(400, "start must be a date in YYYY-MM-DD form")
    return _court_call(cause_list.preview, first, days)


@app.get("/api/hearings", dependencies=[guard("GET /api/hearings")])
def hearings_board(start: Optional[str] = None, days: int = 1):
    """Hearings on published lists from `start` for `days` days, plus earlier hearings with no outcome recorded."""
    try:
        first = date.fromisoformat(start) if start else date.today()
    except ValueError:
        raise HTTPException(400, "start must be a date in YYYY-MM-DD form")
    return _court_call(staff_api.hearing_board, first, days)


@app.get("/api/cause-lists/{cause_list_id}", dependencies=[guard("GET /api/cause-lists/{cause_list_id}")])
def cause_list_get(cause_list_id: int):
    def run(s):
        rows = s.select("cause_lists", {"id": cause_list_id})
        if not rows:
            raise LookupError(f"No cause list {cause_list_id}")
        return {**{k: rows[0][k] for k in ("id", "status", "start_date", "metrics", "explanation", "approved_by")},
                "listings": s.select("listings", {"cause_list_id": cause_list_id}, order="day, bench_id, slot_start")}
    return _court_call(run)


@app.post("/api/cause-lists/{cause_list_id}/publish")
def cause_list_publish(cause_list_id: int, principal: Principal = guard("POST /api/cause-lists/{cause_list_id}/publish")):
    return _court_call(cause_list.publish, cause_list_id, principal.actor, principal.role)


@app.post("/api/cause-lists/{cause_list_id}/reject")
def cause_list_reject(cause_list_id: int, body: Dict[str, str] = None,
                      principal: Principal = guard("POST /api/cause-lists/{cause_list_id}/reject")):
    return _court_call(cause_list.reject, cause_list_id, principal.actor, principal.role, (body or {}).get("note", ""))


class SlotIn(BaseModel):
    action: str                      # accept | move | hold
    day: Optional[str] = None
    bench_id: Optional[str] = None
    hold_until: Optional[str] = None
    cause_list_id: Optional[int] = None  # the draft on screen


@app.post("/api/cases/{case_id:path}/accept-slot")
def accept_slot(case_id: str, body: SlotIn, principal: Principal = guard("POST /api/cases/{case_id:path}/accept-slot")):
    return _court_call(cause_list.accept_slot, case_id, body.action, principal.actor, principal.role,
                       body.day, body.bench_id, body.hold_until, body.cause_list_id)


class OutcomeIn(BaseModel):
    outcome: str                     # heard | adjourned | disposed | not_reached
    reason: Optional[str] = None
    next_date: Optional[str] = None


@app.post("/api/hearings/{hearing_id}/outcome")
def hearing_outcome(hearing_id: int, body: OutcomeIn, principal: Principal = guard("POST /api/hearings/{hearing_id}/outcome")):
    return _court_call(cause_list.record_outcome, hearing_id, body.outcome, principal.actor, principal.role,
                       body.reason, body.next_date)


@app.get("/api/today", dependencies=[guard("GET /api/today")])
def today_counters():
    return _court_call(cause_list.today_counters)


@app.get("/api/docket", dependencies=[guard("GET /api/docket")])
def docket(band: str = "", case_type: str = "", flag: str = "", deferred3: bool = False, needs_review: bool = False,
           custody: bool = False, past_deadline: bool = False, q: str = "", limit: int = 200, not_listed: bool = False):
    return _court_call(staff_api.docket, band, case_type, flag, deferred3, needs_review, custody, past_deadline, q, limit,
                       not_listed)


@app.get("/api/cases/{case_id:path}/detail", dependencies=[guard("GET /api/cases/{case_id:path}/detail")])
def case_detail(case_id: str):
    out = _court_call(staff_api.case_detail, case_id)
    if out is None:
        raise HTTPException(404, f"No case {case_id}")
    return out


@app.get("/api/documents/{doc_id}/pages/{page}", dependencies=[guard("GET /api/documents/{doc_id}/pages/{page}")])
def document_page(doc_id: str, page: int):
    if db.is_advocate_document(doc_id):
        raise HTTPException(404, "No such document")
    out = _court_call(staff_api.source_page, doc_id, page)
    if out is None:
        raise HTTPException(404, "No such document")
    return out


@app.post("/api/advocate/workspaces", dependencies=[guard("POST /api/advocate/workspaces")])
def create_advocate_workspace():
    return advocate.create_workspace()


@app.post("/api/advocate/documents", dependencies=[guard("POST /api/advocate/documents")])
def upload_advocate_document(body: AdvocateDocumentIn):
    try:
        data = base64.b64decode(body.content_base64, validate=True)
    except (ValueError, binascii.Error):
        raise HTTPException(400, "The uploaded file is not valid base64")
    try:
        return advocate.upload_document(body.workspace_token, body.filename, data)
    except advocate.AdvocateError as exc:
        raise HTTPException(exc.status, str(exc))


@app.post("/api/advocate/documents/{doc_id}/insights",
          dependencies=[guard("POST /api/advocate/documents/{doc_id}/insights")])
def advocate_document_insight(doc_id: str, body: AdvocateInsightIn):
    try:
        return advocate.generate_insight(body.workspace_token, doc_id, body.insight_type, body.user_guidance)
    except advocate.AdvocateError as exc:
        raise HTTPException(exc.status, str(exc))


@app.post("/api/advocate/documents/{doc_id}/preview",
          dependencies=[guard("POST /api/advocate/documents/{doc_id}/preview")])
def advocate_document_preview(doc_id: str, body: AdvocateDocumentPreviewIn):
    try:
        uploaded = advocate.get_document_file(body.workspace_token, doc_id)
        media_type = mimetypes.guess_type(uploaded["filename"])[0] or "application/octet-stream"
        return Response(
            content=uploaded["data"],
            media_type=media_type,
            headers={"Content-Disposition": "inline"},
        )
    except advocate.AdvocateError as exc:
        raise HTTPException(exc.status, str(exc))


@app.post("/api/advocate/documents/{doc_id}/chat",
          dependencies=[guard("POST /api/advocate/documents/{doc_id}/chat")])
def advocate_document_chat(doc_id: str, body: AdvocateChatIn):
    try:
        messages = [message.model_dump() for message in body.messages]
        return advocate.chat_with_document(body.workspace_token, doc_id, messages)
    except advocate.AdvocateError as exc:
        raise HTTPException(exc.status, str(exc))


@app.post("/api/advocate/documents/{doc_id}/chat/prepare",
          dependencies=[guard("POST /api/advocate/documents/{doc_id}/chat/prepare")])
def advocate_document_chat_prepare(doc_id: str, body: AdvocateChatPrepareIn):
    try:
        return advocate.prepare_document_chat(body.workspace_token, doc_id)
    except advocate.AdvocateError as exc:
        raise HTTPException(exc.status, str(exc))


@app.post("/api/advocate/studio", dependencies=[guard("POST /api/advocate/studio")])
def advocate_document_studio(body: AdvocateStudioIn):
    try:
        return document_studio.process(body.operation, body.files, body.options)
    except document_studio.StudioError as exc:
        raise HTTPException(exc.status, str(exc))


@app.get("/api/whoami")
def whoami(principal: Principal = guard("GET /api/whoami")):
    """The role the token gives (the UI shows tabs by role; the server still checks every call)."""
    return {"role": principal.role, "actor": principal.actor, "demo_mode": config.DEMO_MODE}


@app.get("/api/rules", dependencies=[guard("GET /api/rules")])
def rules_explained():
    """Scoring weights, band cut-offs, deadlines, scheduling order and Sec. 479 rules, read from the code."""
    return staff_api.rules()


@app.get("/api/insights/weekly", dependencies=[guard("GET /api/insights/weekly")])
def insights_weekly():
    return _court_call(staff_api.weekly)


@app.post("/api/jobs/{name}/run")
def run_job(name: str, principal: Principal = guard("POST /api/jobs/{name}/run")):
    """'Run now' for undertrial_scan | aging_update | weekly_cause_list | daily_topup."""
    try:
        out = jobs.run(name)
    except KeyError as exc:
        raise HTTPException(404, str(exc))
    audit.record(principal, "job_run", f"job:{name}", run_id=out.get("run_id"))
    return out


# ----------------------------------------------------------------------------- intake (staff; work runs in nyayavedika.worker)
def _intake_call(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except intake.IntakeError as exc:
        raise HTTPException(exc.status, {"message": exc.message, "files": exc.files} if exc.files else exc.message)


@app.get("/api/intake/limits", dependencies=[guard("GET /api/intake/limits")])
def intake_limits():
    return intake.limits()


@app.post("/api/intake/batches", status_code=202)
def intake_create(files: List[UploadFile] = File(default=[]), mode: str = Form("separate"),
                  case_number: Optional[str] = Form(None), relative_paths: List[str] = Form(default=[]),
                  text: Optional[str] = Form(None), principal: Principal = guard("POST /api/intake/batches")):
    """Multipart: files[], mode (separate | one_case | existing_case), case_number, relative_paths[], text. Replies 202."""
    real = [f for f in files if not intake.is_junk(f.filename or "")]
    if len(real) > config.DEMO_MAX_FILES:  # checked again inside intake; refuse before reading any bytes
        raise HTTPException(400, f"Demo mode: up to {config.DEMO_MAX_FILES} files at a time. This batch has {len(real)} files.")
    cap = config.DEMO_MAX_FILE_MB * 1024 * 1024 + 1  # read at most limit + 1 byte, enough to reject an oversize file
    payload = [(f.filename or "file", f.file.read(cap)) for f in files]
    return _intake_call(intake.create_batch, payload, mode, case_number, relative_paths, text, principal.actor)


@app.get("/api/intake/batches/{batch_id}", dependencies=[guard("GET /api/intake/batches/{batch_id}")])
def intake_status(batch_id: str):
    return _intake_call(intake.batch_status, batch_id)


@app.post("/api/intake/batches/{batch_id}/jobs/{job_id}/retry")
def intake_retry(batch_id: str, job_id: str,
                 principal: Principal = guard("POST /api/intake/batches/{batch_id}/jobs/{job_id}/retry")):
    out = _intake_call(intake.retry_job, batch_id, job_id)
    audit.record(principal, "intake_retry", f"job:{job_id}", batch_id=batch_id)
    return out


@app.post("/api/intake/rows")
def intake_rows(file: UploadFile = File(...), principal: Principal = guard("POST /api/intake/rows")):
    """Structured docket rows (CSV / JSON) straight to cases; capped at DEMO_MAX_FILES rows in demo mode."""
    return _intake_call(intake.load_rows, file.filename or "rows.csv", file.file.read(), principal.actor, principal.role)


@app.patch("/api/cases/{case_id:path}")
def patch_case(case_id: str, body: Dict[str, Any], principal: Principal = guard("PATCH /api/cases/{case_id:path}")):
    """Staff correct extracted fields; the case is re-scored and the change is written to audit_log."""
    return _intake_call(intake.patch_case, case_id, body, principal.actor, principal.role)


# ----------------------------------------------------------------------------- direct tools
@app.get("/api/cases", dependencies=[guard("GET /api/cases")])
def get_cases():
    return {"cases": db.list_cases()}


@app.post("/api/cases", dependencies=[guard("POST /api/cases")])
def put_cases(cases: List[Dict[str, Any]]):
    if not all(isinstance(c, dict) and c.get("case_id") for c in cases):
        raise HTTPException(400, "Each case needs a case_id")
    return {"loaded": store.upsert_cases(cases, {r["case_id"]: r for r in triage.triage_all(cases)}, source="csv")}


@app.post("/api/triage", dependencies=[guard("POST /api/triage")])
def triage_endpoint(body: Dict[str, Any] = None):
    cases = (body or {}).get("cases") or db.list_cases()
    results = triage.triage_all(cases)
    return {"results": results[:300], "stats": triage.backlog_stats(results)}


@app.post("/api/legal-problem/research", dependencies=[guard("POST /api/legal-problem/research")])
def legal_problem_research_endpoint(body: LegalProblemResearchIn):
    try:
        return legal_problem.research(body.description, body.language, body.jurisdiction)
    except legal_problem.ResearchUnavailable as exc:
        raise HTTPException(503, str(exc))
    except legal_problem.InvalidResearchOutput as exc:
        raise HTTPException(502, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception("Citizen legal-problem research failed: %s", type(exc).__name__)
        raise HTTPException(502, "Legal research could not be completed. No answer was generated; please try again.")


@app.post("/api/legal-problem/chat", dependencies=[guard("POST /api/legal-problem/chat")])
def legal_problem_chat_endpoint(body: LegalProblemChatIn):
    try:
        return legal_problem.chat_turn(body.messages, body.language)
    except legal_problem.ResearchUnavailable as exc:
        raise HTTPException(503, str(exc))
    except legal_problem.InvalidResearchOutput as exc:
        raise HTTPException(502, str(exc))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    except Exception as exc:
        logger.exception("Citizen legal-problem chat failed: %s", type(exc).__name__)
        raise HTTPException(502, "The conversation could not be completed. No answer was generated; please try again.")


@app.post("/api/legal-aid", dependencies=[guard("POST /api/legal-aid")])
def legal_aid_endpoint(body: LegalAidIn):
    applicant = {**body.applicant, **({"district": body.district} if body.district else {}),
                 **({"state": body.state} if body.state else {})}
    elig = legal_aid.check_eligibility(applicant)
    impact.record("legal_aid_check", eligible=elig["eligible"], outcome=elig["outcome"], channel="form")
    impact.record("citizen_session", channel="form", engine="rules")   # the form is a front door of its own
    status = "drafted" if body.draft else "checked"
    with store.connect() as s:  # categories, district and outcome only - never names or numbers
        elig["request_id"] = s.insert("legal_aid_requests", [{
            "channel": "web", "district": body.district or None, "state": elig["state"], "language": body.language,
            "eligible": elig["eligible"], "grounds": [g["clause"] for g in elig["grounds"]], "status": status,
            "source": "web", "created_at": datetime.now(timezone.utc)}], returning="id")
    elig["status"], elig["what_happens_next"] = status, legal_aid.WHAT_NEXT[status]
    if body.draft:
        elig["draft"] = legal_aid.draft_application(applicant, elig, body.problem, body.language)
        impact.record("legal_aid_application", engine=elig["draft"]["engine"])
    return elig


@app.post("/api/legal-aid/explain", dependencies=[guard("POST /api/legal-aid/explain")])
def legal_aid_explain(body: LegalAidIn):
    """The 5-question result in plain words: the rules decide, the legal-aid index supplies cited passages, one
    fast model call explains (template when offline). Nothing is stored."""
    applicant = {**body.applicant, **({"district": body.district} if body.district else {}),
                 **({"state": body.state} if body.state else {})}
    return legal_aid.explain(legal_aid.check_eligibility(applicant), body.problem or "", body.language or "English")


@app.post("/api/legal-aid/ask", dependencies=[guard("POST /api/legal-aid/ask")])
def legal_aid_ask(body: LegalAidAskIn):
    """Answer an optional question from the local legal-aid index, then official web sources if needed."""
    question = body.question.strip()
    if not question:
        raise HTTPException(400, "Enter a question")
    if len(question) > 1500:
        raise HTTPException(413, "Question is too long (1500 character limit)")
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,80}", body.question_session):
        raise HTTPException(400, "Start a new legal-aid session and try again.")
    if len(body.documents) > legal_aid.MAX_QUESTION_DOCUMENTS:
        raise HTTPException(413, f"Attach no more than {legal_aid.MAX_QUESTION_DOCUMENTS} documents per question.")
    if legal_aid.followups_used(body.question_session) >= legal_aid.MAX_FOLLOWUPS:
        raise HTTPException(429, f"This session has reached its {legal_aid.MAX_FOLLOWUPS}-question follow-up limit. "
                                 "Start a new legal-aid session to continue.")

    text_parts, total_size = [], 0
    names = []
    for doc in body.documents:
        pages, size = _document_pages(doc)
        total_size += size
        if total_size > config.MAX_UPLOAD_BYTES:
            raise HTTPException(413, "Combined documents exceed the upload limit")
        names.append(doc.filename)
        text_parts.extend(f"[{doc.filename}, page {page['page']}]\n{page['text']}" for page in pages
                          if (page.get("text") or "").strip())
    document_text = "\n\n".join(text_parts)
    if len(document_text) > 20000:
        raise HTTPException(413, "Attached documents contain too much text for one question (20,000 character limit)")
    answer = legal_aid.answer_question(question, body.language or "English", document_text,
                                       ", ".join(names) or "Uploaded document")
    try:
        answer["followups_used"] = legal_aid.record_followup(body.question_session)
    except legal_aid.FollowupLimitReached as exc:
        raise HTTPException(429, str(exc))
    answer["followups_limit"] = legal_aid.MAX_FOLLOWUPS
    return answer


@app.post("/api/legal-aid/application.docx", dependencies=[guard("POST /api/legal-aid/application.docx")])
def legal_aid_docx(body: LegalAidIn):
    """Word draft of the Sec. 12 application, built in memory; nothing personal is stored."""
    from nyayavedika.docgen import legal_aid_docx as docgen
    data = docgen.build_application_docx({"applicant": body.applicant, "problem": body.problem,
                                          "district": body.district, "state": body.state})
    impact.record("legal_aid_application", engine="docx")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", body.district or "district").strip("_") or "district"
    return Response(content=data, media_type=DOCX_TYPE, headers={
        "Content-Disposition": f'attachment; filename="legal_aid_application_{slug}_{date.today().isoformat()}.docx"'})


@app.get("/api/legal-aid/topics", dependencies=[guard("GET /api/legal-aid/topics")])
def legal_aid_topics():
    """The curated legal_info.html entries (rights, procedures, helplines) with their official sources."""
    from nyayavedika import legal_aid_kb
    return legal_aid_kb.topics()


@app.get("/api/legal-aid/kb", dependencies=[guard("GET /api/legal-aid/kb")])
def legal_aid_kb_search(q: str, top_k: int = 4):
    """Knowledge passages with citations (primary sources first)."""
    from nyayavedika import legal_aid_kb
    return legal_aid_kb.search(q, top_k)


@app.get("/api/legal-aid/state-fact", dependencies=[guard("GET /api/legal-aid/state-fact")])
def legal_aid_state_fact(state: str, key: str = "income_limit"):
    """Table first, trusted web search when missing or stale; always returns source and date to display."""
    return legal_aid.get_state_fact(state, key)


@app.post("/api/draft", dependencies=[guard("POST /api/draft")])
def draft_endpoint(body: Dict[str, str]):
    return drafting.draft(body.get("section", ""), body.get("context", ""), body.get("instructions", ""))


@app.get("/api/drafting/sections", dependencies=[guard("GET /api/drafting/sections")])
def drafting_sections():
    return {k: v["name"] for k, v in drafting.SECTIONS.items()}


@app.post("/api/schedule", dependencies=[guard("POST /api/schedule")])
def schedule_endpoint(body: RegistryIn):
    """DRAFT-ONLY preview: nothing is saved, no listings are created. Use /api/cause-lists/draft + publish."""
    start = date.fromisoformat(body.start_date) if body.start_date else date.today()
    plan = scheduler.build_cause_list(triage.triage_all(db.list_cases(body.court_id)), start, body.days, body.benches)
    return {"draft_only": True, "note": "Preview only - not saved and not published; the Registrar approves real lists.",
            **plan}


@app.post("/api/summarize/offline", dependencies=[guard("POST /api/summarize/offline")])
def summarize_offline(body: DocIn):
    return offline_summary.summarize(body.text or "", body.language)


# ----------------------------------------------------------------------------- impact
@app.post("/api/reach/{door}")
def record_reach(door: Literal["public", "citizen", "advocate", "staff"], body: ReachIn):
    try:
        visitor_hash = impact.reach_hash(body.browser_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, "browser_id must be a UUID v4") from exc
    db.register_reach(visitor_hash, door)
    return {"ok": True}


@app.delete("/api/reach")
def withdraw_reach(body: ReachIn):
    try:
        visitor_hash = impact.reach_hash(body.browser_id)
    except (ValueError, AttributeError) as exc:
        raise HTTPException(400, "browser_id must be a UUID v4") from exc
    db.delete_reach(visitor_hash)
    return {"ok": True}


@app.get("/api/impact", dependencies=[guard("GET /api/impact")])
def impact_summary():
    report = impact.summary()
    with store.connect() as s:
        feedback_mod.ensure_table(s)
        report["field_feedback"] = feedback_mod.summarise(s.select("field_feedback"))
    return report


@app.get("/api/demo/metrics")
def demo_impact_metrics(response: Response):
    """Public, aggregate-only metrics for hackathon demos; detailed impact data remains staff-only."""
    response.headers["Cache-Control"] = "no-store"
    return impact.demo_summary()


@app.get("/api/impact/export.csv", response_class=PlainTextResponse,
         dependencies=[guard("GET /api/impact/export.csv")])
def impact_export():
    return impact.export_csv()


@app.post("/api/feedback")
def feedback(body: FeedbackIn, principal: Principal = guard("POST /api/feedback")):
    if not 1 <= body.rating <= 5:
        raise HTTPException(400, "rating must be 1-5")
    db.insert(db.feedback, feature=body.feature, role=principal.role, rating=body.rating,
              comment=documents.redact_pii(body.comment)[:1000])
    impact.record("feedback", body.rating, feature=body.feature, role=principal.role)
    return {"ok": True}


# ----------------------------------------------------------------------------- field feedback (landing page)
def _feedback_error(exc):
    return HTTPException(exc.status, exc.message)


@app.get("/api/field-feedback")
def field_feedback_wall(principal: Principal = guard("GET /api/field-feedback")):
    """Short cards for the landing page (published entries only) plus summary numbers over all responses."""
    with store.connect() as s:
        return feedback_mod.public(s)


@app.get("/api/field-feedback/all")
def field_feedback_all(principal: Principal = guard("GET /api/field-feedback/all")):
    """All published feedback entries, without the landing-page card limit."""
    with store.connect() as s:
        return feedback_mod.public(s, limit=None)


@app.post("/api/field-feedback")
def field_feedback_submit(body: Dict[str, Any], principal: Principal = guard("POST /api/field-feedback")):
    try:
        with store.connect() as s:
            out = feedback_mod.submit(s, body, principal.role)
    except feedback_mod.FeedbackError as exc:
        raise _feedback_error(exc)
    impact.record("feedback", float(body.get("rating") or 0), feature="landing", role=str(body.get("role") or ""))
    return out


@app.post("/api/field-feedback/{feedback_id}/hide")
def field_feedback_hide(feedback_id: int, principal: Principal = guard("POST /api/field-feedback/{feedback_id}/hide")):
    try:
        with store.connect() as s:
            out = feedback_mod.hide(s, feedback_id)
    except feedback_mod.FeedbackError as exc:
        raise _feedback_error(exc)
    audit.record(principal, "field_feedback_hide", f"field_feedback:{feedback_id}")
    return out


# ----------------------------------------------------------------------------- impact evidence reports
def _report_call(fn, *args):
    try:
        with store.connect() as s:
            return fn(s, *args)
    except impact_reports.ReportError as exc:
        raise HTTPException(exc.status, exc.message)


@app.get("/api/impact-reports/options")
def impact_report_options():
    """Public: the choices the shareable form draws (roles, features, tasks, outcomes)."""
    return impact_reports.options()


@app.post("/api/impact-reports")
def impact_report_submit(body: Dict[str, Any], request: Request):
    """Public: one report from the shareable form (/impact-report). No token needed; consent required."""
    if not impact_reports.rate_ok(request.client.host if request.client else ""):
        raise HTTPException(429, "Too many reports from this connection. Please try again in an hour.")
    out = _report_call(impact_reports.submit, body)
    impact.record("impact_report", 1, role=str(body.get("role") or ""))
    return out


@app.get("/api/impact-reports", dependencies=[guard("GET /api/impact-reports")])
def impact_report_list(status: str = ""):
    """Staff: every report with identity details, for verification. Never public."""
    return _report_call(impact_reports.listing, status)


@app.get("/api/impact-reports/summary", dependencies=[guard("GET /api/impact-reports/summary")])
def impact_report_summary():
    return _report_call(impact_reports.summary)


@app.get("/api/impact-reports/export.csv", response_class=PlainTextResponse,
         dependencies=[guard("GET /api/impact-reports/export.csv")])
def impact_report_export():
    return PlainTextResponse(_report_call(impact_reports.export_csv), media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="impact_reports_{date.today().isoformat()}.csv"'})


@app.post("/api/impact-reports/{report_id}/verify")
def impact_report_verify(report_id: int, body: Dict[str, str],
                         principal: Principal = guard("POST /api/impact-reports/{report_id}/verify")):
    """Staff: mark a report verified / rejected after checking the person (e.g. Bar Council roll)."""
    out = _report_call(impact_reports.verify, report_id, (body or {}).get("status", ""), principal.actor,
                       (body or {}).get("note", ""))
    audit.record(principal, f"impact_report_{out['status']}", f"impact_report:{report_id}")
    return out


@app.post("/api/legal-aid/{request_id}/outcome")
def legal_aid_outcome(request_id: int, body: Dict[str, str],
                      principal: Principal = guard("POST /api/legal-aid/{request_id}/outcome")):
    """Partner DLSA / paralegal reports what happened next: checked, drafted, applied, lawyer_assigned, closed."""
    status = body.get("status", "applied")
    if status not in legal_aid.STATUS_FLOW:
        raise HTTPException(400, f"status must be one of {', '.join(legal_aid.STATUS_FLOW)}")
    audit.record(principal, "legal_aid_outcome", f"legal_aid_request:{request_id}", status=status)
    dated = {"applied": "applied_on", "lawyer_assigned": "lawyer_assigned_on", "closed": "resolved_on"}
    with store.connect() as s:
        s.update("legal_aid_requests", {"id": request_id},
                 {"status": status, **({dated[status]: date.today()} if status in dated else {})})
    impact.record("legal_aid_outcome", status=status)
    return {"ok": True, "status": status, "what_happens_next": legal_aid.WHAT_NEXT[status]}


@app.get("/api/alerts/{alert_id}/release.docx")
def release_docx(alert_id: int, principal: Principal = guard("GET /api/alerts/{alert_id}/release.docx")):
    """Word copy of the Sec. 479 release draft with the lawyer checklist ([to be verified] placeholders)."""
    from nyayavedika.docgen import legal_aid_docx as docgen
    with store.connect() as s:
        rows = s.select("alerts", {"id": alert_id})
    if not rows:
        raise HTTPException(404, f"No alert {alert_id}")
    if principal.role == auth.LAWYER and not undertrial_watch.has_counsel_on_record(rows[0]):
        raise HTTPException(403, "The court registry must record counsel on the alert before counsel can access it.")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", rows[0]["case_id"] or "case").strip("_")
    return Response(content=docgen.build_release_docx(rows[0]), media_type=DOCX_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="release_application_{slug}.docx"'})


@app.get("/api/alerts/{alert_id}/superintendent.docx",
         dependencies=[guard("GET /api/alerts/{alert_id}/superintendent.docx")])
def superintendent_docx(alert_id: int, language: str = "en"):
    """Word copy of the review-only custody-record request for a Section 479 alert."""
    from nyayavedika.docgen import legal_aid_docx as docgen
    if language not in ("en", "hi", "te"):
        raise HTTPException(400, "language must be 'en', 'hi' or 'te'")
    with store.connect() as s:
        rows = s.select("alerts", {"id": alert_id})
    if not rows:
        raise HTTPException(404, f"No alert {alert_id}")
    alert = rows[0]
    if alert.get("kind") not in ("undertrial_release", "release_review_request"):
        raise HTTPException(409, "This alert is not a Section 479 release review.")
    case = store.get_case(alert.get("case_id") or "")
    slug = re.sub(r"[^A-Za-z0-9]+", "_", alert.get("case_id") or "case").strip("_")
    data = {**(case or {}), **alert}
    return Response(content=docgen.build_superintendent_docx(data, language), media_type=DOCX_TYPE,
                    headers={"Content-Disposition": f'attachment; filename="custody_record_review_request_{slug}_{language}.docx"'})


class _CachedStatic(StaticFiles):
    """Every page references its assets with a ?v= version, so a versioned asset can be cached by the browser for a
    day; an unversioned request still revalidates. i18n.json is fetched with cache: "no-cache" and keeps working."""

    async def get_response(self, path, scope):
        response = await super().get_response(path, scope)
        if response.status_code == 200:
            versioned = b"v=" in (scope.get("query_string") or b"")
            response.headers["Cache-Control"] = "public, max-age=86400" if versioned else "no-cache"
        return response


app.mount("/static", _CachedStatic(directory=ROOT / "static"), name="static")


@app.get("/favicon.ico", include_in_schema=False)
def favicon():
    return FileResponse(ROOT / "static" / "favicon.svg", media_type="image/svg+xml")


@app.get("/")
def index():
    """Landing page for the three role-specific portals."""
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/how-it-works", include_in_schema=False)
def how_it_works_page():
    return HTMLResponse(public_docs.render_page("how-it-works"))


@app.get("/research-evidence", include_in_schema=False)
def research_evidence_page():
    return HTMLResponse(public_docs.render_page("research-evidence"))


@app.get("/advocate")
def advocate_app():
    """Serve the separate lawyer-role Document Studio and AI insights portal."""
    return FileResponse(ROOT / "static" / "advocate.html")


@app.get("/staff")
def staff_app():
    return FileResponse(ROOT / "static" / "staff.html")


@app.get("/citizen")
def citizen_portal():
    return FileResponse(ROOT / "static" / "citizen.html")


@app.get("/feedback")
def feedback_wall_page():
    return FileResponse(ROOT / "static" / "feedback-wall.html")


@app.get("/impact-report")
def impact_report_page():
    """The shareable evidence form. Add ?role=advocate (or citizen, court_staff ...) to preselect the role."""
    return FileResponse(ROOT / "static" / "impact-report.html")


@app.get("/impact-report/review")
def impact_review_page():
    """Staff verification desk for impact reports (the data itself needs a staff token)."""
    return FileResponse(ROOT / "static" / "impact-review.html")


@app.get("/metrics")
def public_metrics_page():
    return FileResponse(ROOT / "static" / "metrics.html")


@app.get("/pilot/template.csv")
def pilot_template_download():
    return FileResponse(
        ROOT / "pilot" / "pilot_log_template.csv",
        media_type="text/csv",
        filename="pilot_log_template.csv",
    )


@app.get("/legal-info")
def legal_info_page():
    return FileResponse(ROOT / config.LEGAL_INFO_HTML)


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=config.HOST, port=config.PORT)
