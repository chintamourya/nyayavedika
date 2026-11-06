"""Staff intake: batches of up to DEMO_MAX_FILES files -> one ingest job per file.

The web request only validates, stores bytes by content hash and writes rows; it never reads or
analyses a document (nyayavedika.worker does). The API layer in server.py is a thin wrapper over this
module, so every rule here is tested without a web server.
"""
import csv
from collections import Counter
import hashlib
import io
import json
import re
import uuid
from datetime import date, datetime, timedelta, timezone
from pathlib import PurePosixPath
from typing import Dict, Iterable, List, Optional, Tuple

from . import config, extraction, scheduler, storage, store, triage

MODES = ("separate", "one_case", "existing_case", "by_folder", "summary_only")
# separate       every file is its own case (a folder named like a case number, e.g. SC-88-2024, still groups its files)
# one_case       all files are one case
# existing_case  attach to a case that is already in the docket
# by_folder      every folder is one case (a folder named like a case number keeps that number)
# summary_only   citizen chat: summarise, create no case
ROW_EXTS = ("csv", "json")
JUNK_NAMES = {".ds_store", "thumbs.db", "desktop.ini", ".gitkeep", ".localized"}
CASE_LIKE = re.compile(r"^(?:[A-Za-z][A-Za-z.()]{0,11}[-_ /.]\d{1,7}(?:[-_ /.]\d{2,4})?|\d{1,7}[-_ /]\d{4})$")


class IntakeError(Exception):
    def __init__(self, status: int, message: str, files: Optional[List[Dict]] = None):
        super().__init__(message)
        self.status, self.message, self.files = status, message, files


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _ext(filename: str) -> str:
    return PurePosixPath((filename or "").replace("\\", "/")).suffix.lower().lstrip(".")


def _norm_path(path: Optional[str]) -> str:
    return "/".join(p for p in (path or "").replace("\\", "/").split("/") if p not in ("", ".", ".."))


def _basename(filename: str) -> str:
    return _norm_path(filename).rsplit("/", 1)[-1] or (filename or "file")


def _folder_of(relative_path: Optional[str]) -> str:
    """'Root/CC-12-2026/fir.pdf' -> 'Root/CC-12-2026'; a bare file name -> ''."""
    parts = _norm_path(relative_path).split("/")
    return "/".join(parts[:-1])


def _folder_case_number(relative_path: Optional[str]) -> Optional[str]:
    """Name of the file's own folder when it looks like a case number ('SC-88-2024/order.pdf' -> 'SC-88-2024').
    A folder called 'Documents' or 'Rahul case papers' is only a folder: it never becomes a case."""
    folder = _folder_of(relative_path)
    name = folder.rsplit("/", 1)[-1] if folder else ""
    return name if CASE_LIKE.match(name) else None


def _generated_folder_case(folder: str, year: int) -> str:
    """by_folder mode: a stable id for a folder without a case number (no names from the path end up in the id)."""
    return f"UPL/{year}/{hashlib.sha1(folder.encode('utf-8')).hexdigest()[:6].upper()}"


def is_junk(name: str) -> bool:
    base = _basename(name).lower()
    return base in JUNK_NAMES or base.startswith(("~$", "._")) or "__macosx" in _norm_path(name).lower().split("/")


def pdf_page_count(data: bytes) -> Optional[int]:
    """Pages in a PDF (pypdf when installed, else a count of page objects); None when it cannot be told."""
    try:
        import pypdf
        return len(pypdf.PdfReader(io.BytesIO(data)).pages)
    except ImportError:
        n = len(re.findall(rb"/Type\s*/Page(?![a-zA-Z])", data))
        return n or None
    except Exception:
        return None  # a damaged PDF is reported by the reader with its own reason


def _check_file(name: str, data: bytes) -> Optional[str]:
    """Reason to reject one file, or None."""
    ext = _ext(name)
    if ext not in config.ALLOWED_EXTS:
        hint = " Scanned images will be accepted once OCR is switched on." if ext in ("png", "jpg", "jpeg", "tif", "tiff") else ""
        return f"File type .{ext or '?'} is not accepted (allowed: {', '.join(config.ALLOWED_EXTS)}).{hint}"
    if not data:
        return "The file is empty"
    limit = config.DEMO_MAX_FILE_MB * 1024 * 1024
    if len(data) > limit:
        return f"The file is {len(data) / 1048576:.1f} MB; the limit is {config.DEMO_MAX_FILE_MB} MB"
    if ext == "pdf":
        pages = pdf_page_count(data)
        if pages and pages > config.DEMO_MAX_PAGES:
            return (f"This PDF has {pages} pages, but the limit is {config.DEMO_MAX_PAGES} pages per file. "
                    f"Split it into files of {config.DEMO_MAX_PAGES} pages or fewer, then upload them together "
                    "as one case if they belong to the same case.")
    return None


def _ts(value) -> Optional[datetime]:
    if not value:
        return None
    t = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    return t if t.tzinfo else t.replace(tzinfo=timezone.utc)


def _job_alive(job: Dict, now: datetime) -> bool:
    """A job that is being read right now (running with a fresh heartbeat), or a fresh upload still waiting for its
    first turn. A job that failed, waits for a retry, or whose worker stopped is not alive: a re-upload restarts it."""
    fresh = now - timedelta(minutes=config.WORKER_STALE_MINUTES)
    if job["status"] == "running":
        return bool(job.get("heartbeat_at")) and _ts(job["heartbeat_at"]) >= fresh
    if job["status"] == "queued" and not job.get("attempts"):
        return (_ts(job.get("created_at")) or now) >= fresh
    return False


def doc_state(s, key: str, now: Optional[datetime] = None) -> Tuple[str, Optional[Dict], Optional[Dict]]:
    """('new' | 'processed' | 'running' | 'retry', document row, live job).
    'retry' covers a failed run, a run waiting for its next attempt, and one whose worker stopped: the upload starts it again."""
    now = now or _now()
    known = s.select("documents", {"doc_id": key})
    if not known:
        return "new", None, None
    doc = known[0]
    if doc["status"] == "processed":
        return "processed", doc, None
    live = next((j for j in s.select("ingest_jobs", {"doc_id": key}) if _job_alive(j, now)), None)
    return ("running", doc, live) if live else ("retry", doc, None)


def create_batch(files: Iterable[Tuple[str, bytes]], mode: str = "separate", case_number: Optional[str] = None,
                 relative_paths: Optional[List[str]] = None, text: Optional[str] = None,
                 actor: str = "demo-staff", db=None) -> Dict:
    """Validate, store and queue. Raises IntakeError(400/404) for batch-level problems.

    Folder rules: the folder a file came from (relative_paths, or a path in the file name) decides its case only in
    `by_folder` mode, or when the folder is named like a case number. System files (.DS_Store, Thumbs.db ...) are
    skipped and do not count against the cap. In `summary_only` mode a file that is already in the system is
    summarised again from the cache (a citizen who re-attaches a file still gets the answer)."""
    files = list(files)
    if text and text.strip():
        files.append(("pasted_text.txt", text.strip().encode("utf-8")))
    if not files:
        raise IntakeError(400, "Send at least one file or paste some text")
    if mode not in MODES:
        raise IntakeError(400, f"mode must be one of {', '.join(MODES)}")
    relative_paths = list(relative_paths or [])
    entries = []  # (display name, folder-aware path, bytes)
    for i, (name, data) in enumerate(files):
        rel = _norm_path(relative_paths[i]) if i < len(relative_paths) and relative_paths[i] else _norm_path(name)
        entries.append((_basename(name), rel if "/" in rel else "", data))
    real = [e for e in entries if not is_junk(e[0]) and not is_junk(e[1] or e[0])]
    if len(real) > config.DEMO_MAX_FILES:
        raise IntakeError(400, f"Demo mode: up to {config.DEMO_MAX_FILES} files at a time, "
                               f"{config.DEMO_MAX_FILE_MB} MB each. This batch has {len(real)} files.")
    if mode == "by_folder" or any(rel for _, rel, _ in real):
        counts = Counter(_folder_of(rel) for _, rel, _ in real)
        if any(count > config.MAX_FILES_PER_FOLDER for count in counts.values()):
            raise IntakeError(400, f"Each folder may contain up to {config.MAX_FILES_PER_FOLDER} files. "
                                   "Move extra files to another folder or remove them.")
    case_number = (case_number or "").strip() or None
    now = _now()
    with store._session(db) as s:
        if mode == "existing_case":
            if not case_number:
                raise IntakeError(400, "Give the case number to attach these files to")
            if not store.get_case(case_number, db=s):
                raise IntakeError(404, f"No case {case_number} in the docket")
        batch_id = uuid.uuid4().hex[:12]
        shared_case = case_number if mode in ("one_case", "existing_case") else None
        if mode == "one_case" and not shared_case:
            shared_case = f"UPL/{now.year}/{batch_id[:6].upper()}"

        results, seen = [], set()
        for name, rel, data in entries:
            item = {"filename": name, "relative_path": rel or None}
            if is_junk(name) or is_junk(rel or name):
                results.append({**item, "status": "skipped", "reason": "System file, ignored"})
                continue
            reason = _check_file(name, data)
            if reason:
                results.append({**item, "status": "rejected", "reason": reason})
                continue
            key = storage.sha256(data)
            if key in seen:
                results.append({**item, "status": "duplicate", "doc_id": key, "reason": "The same file appears twice in this batch"})
                continue
            state, doc, live = doc_state(s, key, now)
            # processed -> attached to its case; being worked on right now -> point to that batch;
            # failed / waiting for a retry / abandoned by a stopped worker -> this upload processes it again.
            # (A citizen summary is always served, from the cache when possible.)
            if state == "processed" and mode != "summary_only":
                results.append({**item, "status": "duplicate", "doc_id": key, "case_id": doc["case_id"],
                                "reason": (f"Already in the system, attached to case {doc['case_id']}" if doc["case_id"]
                                           else "Already in the system (read earlier)")})
                continue
            if state == "running" and mode != "summary_only":
                results.append({**item, "status": "duplicate", "doc_id": key, "case_id": doc["case_id"], "batch_id": live["batch_id"],
                                "reason": f"Already in the system and still being processed (batch {live['batch_id']}, "
                                          f"stage: {live['stage']}) - the result will appear there"})
                continue
            known, was_failed = [doc] if doc else [], state == "retry"
            seen.add(key)
            storage.put(data, key)
            if mode in ("one_case", "existing_case"):
                planned = shared_case
            elif mode == "by_folder":
                planned = _folder_case_number(rel) or (_generated_folder_case(_folder_of(rel), now.year) if rel else None)
            elif mode == "summary_only":
                planned = None
            else:  # separate
                planned = _folder_case_number(rel) or (case_number if len(real) == 1 else None)
            results.append({**item, "status": "queued", "doc_id": key, "job_id": uuid.uuid4().hex, "case_id": planned,
                            "_known": bool(known), "_failed": was_failed})

        accepted = [r for r in results if r["status"] == "queued"]
        if not accepted and not any(r["status"] in ("duplicate", "skipped") for r in results):
            raise IntakeError(400, "No file was accepted", results)
        s.insert("ingest_batches", [{
            "batch_id": batch_id, "mode": mode, "file_count": len(accepted), "case_number": shared_case or case_number,
            "status": "queued" if accepted else "done", "created_by": actor, "created_at": now, "updated_at": now,
            "files_rejected": [r for r in results if r["status"] != "queued"]}])
        for i, r in enumerate(accepted):
            at = now + timedelta(microseconds=i)  # keeps the claim order = upload order
            if r["_known"]:
                if r["_failed"]:  # take the document over for this batch; a processed one is left as it is
                    s.update("documents", {"doc_id": r["doc_id"]}, {"batch_id": batch_id, "status": "queued"})
                    # earlier jobs still waiting (a delayed retry, or a stopped worker's job) stand down for this one
                    for old in s.select("ingest_jobs", {"doc_id": r["doc_id"], "status": ["queued", "running"]}):
                        s.update("ingest_jobs", {"job_id": old["job_id"]}, {
                            "status": "failed", "stage": "failed", "updated_at": now,
                            "error": f"Replaced by a new upload in batch {batch_id}"})
            else:
                s.insert("documents", [{"doc_id": r["doc_id"], "batch_id": batch_id, "filename": r["filename"],
                                        "storage_uri": storage.uri(r["doc_id"]), "status": "queued", "created_at": at}])
            s.insert("ingest_jobs", [{"job_id": r["job_id"], "batch_id": batch_id, "doc_id": r["doc_id"],
                                      "case_id": r["case_id"], "filename": r["filename"], "relative_path": r["relative_path"],
                                      "stage": "queued", "status": "queued", "attempts": 0, "available_at": at,
                                      "created_at": at, "updated_at": at}])
        s.commit()
    for r in results:
        r.pop("_known", None)
        r.pop("_failed", None)
    return {"batch_id": batch_id, "mode": mode, "status": "queued" if accepted else "done",
            "case_number": shared_case or case_number, "limits": limits(), "files": results}


def limits() -> Dict:
    return {"max_files": config.DEMO_MAX_FILES, "max_file_mb": config.DEMO_MAX_FILE_MB,
            "max_files_per_folder": config.MAX_FILES_PER_FOLDER, "max_pages_per_file": config.DEMO_MAX_PAGES,
            "allowed_types": config.ALLOWED_EXTS, "demo_mode": config.DEMO_MODE}


def batch_status(batch_id: str, db=None) -> Dict:
    with store._session(db) as s:
        batches = s.select("ingest_batches", {"batch_id": batch_id})
        if not batches:
            raise IntakeError(404, f"No batch {batch_id}")
        jobs = s.select("ingest_jobs", {"batch_id": batch_id}, order="created_at")
    b = batches[0]
    files = [{"job_id": j["job_id"], "filename": j["filename"], "doc_id": j["doc_id"], "case_id": j["case_id"],
              "stage": j["stage"], "status": j["status"], "attempts": j["attempts"], "error": j["error"],
              "result": j["result"]} for j in jobs]
    pending = [f for f in files if f["status"] in ("queued", "running")]
    failed = [f for f in files if f["status"] == "failed"]
    status = "running" if pending else ("done_with_errors" if failed else "done")
    return {"batch_id": batch_id, "mode": b["mode"], "case_number": b["case_number"], "status": status,
            "created_at": b["created_at"], "files": files, "not_queued": b.get("files_rejected") or [],
            "poll_seconds": config.WORKER_POLL_SECONDS}


def retry_job(batch_id: str, job_id: str, db=None) -> Dict:
    with store._session(db) as s:
        jobs = s.select("ingest_jobs", {"job_id": job_id, "batch_id": batch_id})
        if not jobs:
            raise IntakeError(404, f"No job {job_id} in batch {batch_id}")
        if jobs[0]["status"] in ("queued", "running"):
            raise IntakeError(409, "This file is already queued or being processed")
        now = _now()
        s.update("ingest_jobs", {"job_id": job_id}, {"status": "queued", "stage": "queued", "attempts": 0, "error": None,
                                                     "heartbeat_at": None, "available_at": now, "updated_at": now})
        s.update("ingest_batches", {"batch_id": batch_id}, {"status": "queued", "updated_at": now})
        s.commit()
    return {"job_id": job_id, "status": "queued"}


# ----------------------------------------------------------------------------- shared case writing
def save_case(s, case: Dict, provenance: Dict, source: str, today: Optional[date] = None) -> Dict:
    """Validate -> provisional score -> upsert case + triage_scores + case_queue_state. Returns the score."""
    today = today or date.today()
    case["review_fields"] = sorted(set(extraction.missing_fields(case)) | set(case.get("review_fields_extra") or []))
    case.pop("review_fields_extra", None)
    case["data_quality"] = "needs_review" if case["review_fields"] else "complete"
    case.setdefault("court_id", "DEMO-DC")
    case.setdefault("status", "pending")
    scored = extraction.provisional_score(case, today)
    store.upsert_case(case, scored, source=source, data_quality=case["data_quality"], field_provenance=provenance, db=s)
    store.insert_triage_scores([scored], triage.RULES_VERSION, db=s)
    qs = store.queue_state(case["case_id"], db=s) or {}
    store.upsert_queue_state([{
        "case_id": case["case_id"], "first_eligible_on": qs.get("first_eligible_on") or today.isoformat(),
        # working days, same as the scheduler and the aging job; a correction may tighten the deadline, never extend it
        "sla_due_on": min(filter(None, [qs.get("sla_due_on"), scheduler.add_working_days(
            today, int(config.SLA_DAYS.get(scored["band"], 30))).isoformat()])),
        "needs_review": case["data_quality"] == "needs_review"}], db=s)
    return scored


def _clean(case: Dict) -> Dict:
    return {k: v for k, v in case.items() if not k.startswith("_") and k not in ("field_provenance", "source")}


# ----------------------------------------------------------------------------- staff corrections
EDITABLE = {"case_type", "stage", "filing_date", "status", "accused_in_custody", "custody_since", "max_sentence_years",
            "first_time_offender", "act", "section", "senior_citizen", "woman_or_child", "disability", "legal_aid",
            "adjournments", "last_hearing_date", "next_hearing_date", "case_number"}
STATUSES = ("pending", "on_hold", "disposed", "transferred")
CUSTODY_FIELDS = {"accused_in_custody", "custody_since", "max_sentence_years", "first_time_offender", "act", "section"}


def _coerce(field: str, value):
    if value in (None, ""):
        return None
    if field in ("filing_date", "custody_since", "last_hearing_date", "next_hearing_date"):
        iso = store._iso_date(value)
        if not iso:
            raise IntakeError(400, f"{field}: give a date as YYYY-MM-DD")
        return iso
    if field in ("accused_in_custody", "first_time_offender", "senior_citizen", "woman_or_child", "disability", "legal_aid"):
        if isinstance(value, bool):
            return value
        if str(value).lower() in ("true", "yes", "1", "false", "no", "0"):
            return str(value).lower() in ("true", "yes", "1")
        raise IntakeError(400, f"{field}: give true or false")
    if field == "case_type" and value not in triage.CASE_TYPES:
        raise IntakeError(400, f"case_type must be one of {', '.join(triage.CASE_TYPES)}")
    if field == "stage" and value not in triage.STAGE_MINUTES:
        raise IntakeError(400, f"stage must be one of {', '.join(triage.STAGE_MINUTES)}")
    if field == "adjournments":
        try:
            return int(value)
        except (TypeError, ValueError):
            raise IntakeError(400, "adjournments: give a whole number")
    if field == "max_sentence_years" and str(value).lower() not in ("life", "death"):
        m = re.search(r"\d+(?:\.\d+)?", str(value))   # "7", 7.0 or "7 years"
        if not m:
            raise IntakeError(400, "max_sentence_years: give a number of years, or life / death")
        return float(m.group(0))
    if field == "status" and value not in STATUSES:
        raise IntakeError(400, f"status must be one of {', '.join(STATUSES)}")
    return value


def patch_case(case_id: str, changes: Dict, actor: str, role: str, db=None) -> Dict:
    """Staff correct fields -> re-score -> triage_scores row + audit_log (before / after)."""
    unknown = set(changes) - EDITABLE
    if unknown:
        raise IntakeError(400, f"These fields cannot be edited: {', '.join(sorted(unknown))}")
    if not changes:
        raise IntakeError(400, "Nothing to change")
    with store._session(db) as s:
        current = store.get_case(case_id, db=s)
        if not current:
            raise IntakeError(404, f"No case {case_id}")
        case, prov = _clean(current), dict(current.get("field_provenance") or {})
        before, after, at = {}, {}, _now().isoformat()
        for field, value in changes.items():
            before[field], after[field] = case.get(field), _coerce(field, value)
            case[field] = after[field]
            prov[field] = {"source": "staff", "actor": actor, "at": at}
        if {"act", "section"} & set(changes) and "max_sentence_years" not in changes and case.get("act") and case.get("section"):
            ref = store.statute(case["act"], case["section"], db=s)  # code, not a person's guess, sets the maximum
            case["max_sentence_years"] = ("life" if ref["life_or_death"] else ref["max_sentence_years"]) if ref else None
            if ref:
                prov["max_sentence_years"] = {"source": "statute_ref", "act": ref["act"], "section": ref["section"]}
        scored = save_case(s, case, prov, current.get("source") or "upload")
        store.audit(actor, role, "case_edit", f"case:{case_id}", {"before": before, "after": after,
                                                                  "band": scored["band"], "score": scored["score"]}, db=s)
        s.commit()
        rescan = None
        if CUSTODY_FIELDS & set(changes):  # custody facts changed: Undertrial Watch re-checks this case now
            from .agents.undertrial_watch import run_scan
            rescan = {k: v for k, v in run_scan(s, case_ids=[case_id]).items() if k != "alert_ids"}
    return {"case_id": case_id, "data_quality": case["data_quality"], "review_fields": case["review_fields"],
            "priority": {k: scored[k] for k in ("score", "band", "flags", "reasons", "recommended_route")},
            "undertrial_rescan": rescan}


# ----------------------------------------------------------------------------- structured rows (CSV / JSON)
BOOL_COLS = {"accused_in_custody", "first_time_offender", "senior_citizen", "woman_or_child", "disability", "legal_aid"}


def _parse_rows(filename: str, data: bytes) -> List[Dict]:
    ext = _ext(filename)
    if ext not in ROW_EXTS:
        raise IntakeError(400, "Structured upload takes a .csv or .json file")
    text = data.decode("utf-8-sig", errors="replace")
    try:
        rows = json.loads(text) if ext == "json" else list(csv.DictReader(io.StringIO(text)))
    except (ValueError, csv.Error) as exc:
        raise IntakeError(400, f"Could not read the {ext.upper()} file: {exc}")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        raise IntakeError(400, "Expected a list of case rows")
    out = []
    for r in rows:
        case = {k.strip(): (v.strip() if isinstance(v, str) else v) for k, v in r.items() if k and v not in (None, "")}
        for k in BOOL_COLS & set(case):
            case[k] = str(case[k]).lower() in ("true", "yes", "1") if not isinstance(case[k], bool) else case[k]
        if "adjournments" in case:
            case["adjournments"] = int(case["adjournments"])
        if isinstance(case.get("advocate_ids"), str):
            case["advocate_ids"] = [a.strip() for a in case["advocate_ids"].split(";") if a.strip()]
        ms = case.get("max_sentence_years")
        if isinstance(ms, str) and ms.replace(".", "", 1).isdigit():
            case["max_sentence_years"] = float(ms)
        out.append(case)
    return out


def load_rows(filename: str, data: bytes, actor: str = "demo-staff", role: str = "staff", db=None) -> Dict:
    rows = _parse_rows(filename, data)
    if not rows:
        raise IntakeError(400, "The file has no rows")
    if config.DEMO_MODE and len(rows) > config.DEMO_MAX_FILES:
        raise IntakeError(400, f"Demo mode: up to {config.DEMO_MAX_FILES} rows at a time. This file has {len(rows)}.")
    if not all(r.get("case_id") for r in rows):
        raise IntakeError(400, "Every row needs a case_id")
    loaded = []
    with store._session(db) as s:
        for case in rows:
            prov = {k: {"source": "csv", "file": filename} for k in case if k != "case_id"}
            scored = save_case(s, dict(case), prov, "csv")
            loaded.append({"case_id": case["case_id"], "band": scored["band"], "score": scored["score"]})
        store.audit(actor, role, "structured_upload", f"file:{filename}", {"rows": len(rows)}, db=s)
        s.commit()
    return {"loaded": len(loaded), "cases": loaded}
