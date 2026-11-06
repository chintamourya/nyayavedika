"""Background worker for intake jobs. ingest_jobs is the queue - no Redis / Celery.

    python -m nyayavedika.worker                 # run forever, WORKER_CONCURRENCY jobs at a time
    python -m nyayavedika.worker --once          # drain what is claimable now, then exit (tests, cron)

Claiming: Postgres uses SELECT ... FOR UPDATE SKIP LOCKED; SQLite (dev) uses a compare-and-set UPDATE.
A running job writes a heartbeat; one silent for WORKER_STALE_MINUTES goes back to the queue.
A failure is retried WORKER_MAX_ATTEMPTS times with a growing delay; the failed row keeps the reason.
Summaries come from nyayavedika.summarise (map-reduce, four outputs, cached per content hash); a case with
several documents gets a case-level merge, and contradictions between documents go to needs_review.
Stages: queued -> reading -> summarising -> extracting -> scored | proposed | needs_review | failed
("proposed": a Critical / release-eligible case got a fast-lane slot in the nearest open draft list).
"""
import argparse
import logging
import threading
import time
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Dict, Optional

from . import cause_list, config, extraction, impact, intake, storage, store, summarise  # config reads .env on import

logger = logging.getLogger("nyayavedika.worker")
HEARTBEAT_SECONDS = config.WORKER_HEARTBEAT_SECONDS


class PermanentError(Exception):
    """Retrying cannot help (unreadable file, missing OCR engine): fail at once with the reason."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


# ----------------------------------------------------------------------------- queue operations
# Two jobs that write the same case (or read the same document) never run at once: siblings of one
# one_case / existing_case / by_folder batch, jobs planned for the same case number (a folder named SC-88-2024 in
# two batches), and two jobs for the same file.
_CANDIDATES = """
    SELECT job_id FROM ingest_jobs j
    WHERE j.status = 'queued' AND (j.available_at IS NULL OR j.available_at <= {now})
      AND NOT EXISTS (SELECT 1 FROM ingest_jobs r
                      WHERE r.status = 'running' AND r.job_id <> j.job_id
                        AND (r.doc_id = j.doc_id
                             OR (r.case_id IS NOT NULL AND r.case_id = j.case_id)
                             OR (r.batch_id = j.batch_id AND EXISTS (SELECT 1 FROM ingest_batches b
                                                                     WHERE b.batch_id = r.batch_id AND b.mode NOT IN ('separate', 'summary_only')))))
    ORDER BY j.created_at"""


def claim(db, now: Optional[datetime] = None) -> Optional[Dict]:
    """Take one claimable job and mark it running (attempts + 1). None when the queue is empty."""
    for _ in range(5):
        job = _claim_once(db, now)
        if job is None or _keep_claim(db, job):
            return job
    return None


def _keep_claim(db, job: Dict) -> bool:
    """Two workers can claim sibling jobs at the same instant; the earliest-created one keeps going, the other
    goes straight back to the queue (attempt not counted)."""
    rows = db.query("""SELECT r.job_id FROM ingest_jobs r
                       WHERE r.status = 'running'
                         AND (r.doc_id = :doc OR (CAST(:case AS TEXT) IS NOT NULL AND r.case_id = :case)
                              OR (r.batch_id = :b AND EXISTS (SELECT 1 FROM ingest_batches b WHERE b.batch_id = r.batch_id
                                                              AND b.mode NOT IN ('separate', 'summary_only'))))
                       ORDER BY r.created_at, r.job_id""",
                    {"b": job["batch_id"], "doc": job["doc_id"], "case": job["case_id"]})
    if not rows or rows[0]["job_id"] == job["job_id"]:
        return True
    db.execute("UPDATE ingest_jobs SET status = 'queued', attempts = attempts - 1 WHERE job_id = :id AND status = 'running'",
               {"id": job["job_id"]})
    db.commit()
    return False


def _claim_once(db, now: Optional[datetime] = None) -> Optional[Dict]:
    now_iso = (now or _now()).isoformat()
    if db.dialect == "postgresql":
        rows = db.query(f"""UPDATE ingest_jobs SET status = 'running', attempts = attempts + 1,
                                   heartbeat_at = CAST(:now AS TIMESTAMPTZ), updated_at = CAST(:now AS TIMESTAMPTZ)
                            WHERE job_id = ({_CANDIDATES.format(now='CAST(:now AS TIMESTAMPTZ)')}
                                            LIMIT 1 FOR UPDATE SKIP LOCKED)
                            RETURNING *""", {"now": now_iso}, table="ingest_jobs")
        db.commit()
        return rows[0] if rows else None
    for cand in db.query(_CANDIDATES.format(now=":now") + " LIMIT 5", {"now": now_iso}):
        rows = db.query("""UPDATE ingest_jobs SET status = 'running', attempts = attempts + 1, heartbeat_at = :now,
                                  updated_at = :now
                           WHERE job_id = :id AND status = 'queued'
                             AND (available_at IS NULL OR available_at <= :now) RETURNING *""",
                        {"now": now_iso, "id": cand["job_id"]}, table="ingest_jobs")
        db.commit()
        if rows:  # compare-and-set won; another worker may have taken the others
            return rows[0]
    return None


def reclaim_stale(db, now: Optional[datetime] = None) -> int:
    """Jobs whose worker died (no heartbeat for WORKER_STALE_MINUTES) go back to the queue, or fail if out of tries."""
    now = now or _now()
    cutoff = now - timedelta(minutes=config.WORKER_STALE_MINUTES)
    stale = [j for j in db.select("ingest_jobs", {"status": "running"})
             if not j["heartbeat_at"] or datetime.fromisoformat(j["heartbeat_at"]) < cutoff]
    for j in stale:
        out_of_tries = j["attempts"] >= config.WORKER_MAX_ATTEMPTS
        db.update("ingest_jobs", {"job_id": j["job_id"], "status": "running"}, {
            "status": "failed" if out_of_tries else "queued", "stage": "failed" if out_of_tries else "queued",
            "error": f"No heartbeat for {config.WORKER_STALE_MINUTES} minutes (worker stopped)"
                     + ("; out of retries" if out_of_tries else "; requeued"),
            "available_at": now, "updated_at": now})
    db.commit()
    if stale:
        logger.warning("requeued %d stale job(s)", len(stale))
    return len(stale)


def _set_stage(db, job: Dict, stage: str) -> None:
    now = _now()
    db.update("ingest_jobs", {"job_id": job["job_id"]}, {"stage": stage, "heartbeat_at": now, "updated_at": now})
    db.commit()


def _fail(db, job: Dict, exc: Exception, permanent: bool) -> str:
    now, attempts = _now(), job["attempts"]
    if permanent or attempts >= config.WORKER_MAX_ATTEMPTS:
        db.update("ingest_jobs", {"job_id": job["job_id"]}, {
            "status": "failed", "stage": "failed", "updated_at": now,
            "error": f"{exc}" + ("" if permanent else f" (gave up after {attempts} attempts)")})
        db.update("documents", {"doc_id": job["doc_id"], "batch_id": job["batch_id"]}, {"status": "failed"})
        db.commit()
        return "failed"
    delay = config.WORKER_RETRY_BASE_SECONDS * 4 ** (attempts - 1)
    db.update("ingest_jobs", {"job_id": job["job_id"]}, {
        "status": "queued", "stage": "queued", "available_at": now + timedelta(seconds=delay), "updated_at": now,
        "error": f"Attempt {attempts} failed: {exc}. Retrying in {delay} s."})
    db.commit()
    return "retry"


class _Heartbeat(threading.Thread):
    def __init__(self, job_id: str):
        super().__init__(daemon=True)
        self.job_id, self.stop = job_id, threading.Event()

    def run(self):
        while not self.stop.wait(HEARTBEAT_SECONDS):
            try:
                with store.connect() as db:
                    db.update("ingest_jobs", {"job_id": self.job_id, "status": "running"}, {"heartbeat_at": _now()})
            except Exception as exc:
                logger.warning("heartbeat failed: %s", exc)


# ----------------------------------------------------------------------------- the pipeline for one file
def _read(job: Dict):
    try:
        pages = storage.pages_or_extract(job["doc_id"], job["filename"])
    except (RuntimeError, ValueError, OSError, ImportError) as exc:  # bad file, or PDF / OCR support not installed
        raise PermanentError(f"Could not read the file: {exc}")
    if len(pages) > config.DEMO_MAX_PAGES:
        raise PermanentError(f"This file has {len(pages)} pages; the demo limit is {config.DEMO_MAX_PAGES} pages per file. "
                             f"Upload the first {config.DEMO_MAX_PAGES} pages (or split the file).")
    if not storage.text_of(pages):
        hint = " Scanned pages need OCR, which is not switched on yet (image uploads come with OCR)." \
            if any(p.get("source") == "needs_ocr_unavailable" for p in pages) else ""
        raise PermanentError("No text could be read from the file." + hint)
    return pages


def _apply_case_merge(db, case: Dict, provenance: Dict) -> Dict:
    """Several documents, one case: case-level reduce; contradictions blank the field and send it to review."""
    case_brief = summarise.merge_case(db, case["case_id"])
    case["case_brief"] = case_brief
    for c in case_brief["conflicts"]:
        if (provenance.get(c["field"]) or {}).get("source") == "staff":
            continue  # a person already settled it
        case[c["field"]] = None  # never pick one of two documents' dates silently
        provenance[c["field"]] = {"status": "conflict", "values": c["values"]}
        case.setdefault("review_fields_extra", []).append(c["field"])
    return case_brief


def _merge(existing: Optional[Dict], case_id: str, fields: Dict, prov: Dict):
    """New facts fill gaps only; what staff or an earlier document already set is kept (Phase 4 merges properly)."""
    if not existing:
        return {"case_id": case_id, **fields}, dict(prov), "upload"
    case, old_prov = intake._clean(existing), dict(existing.get("field_provenance") or {})
    for k, v in fields.items():
        if case.get(k) in (None, ""):
            case[k] = v
            old_prov[k] = prov.get(k)
    for k, p in prov.items():
        old_prov.setdefault(k, p)
    return case, old_prov, existing.get("source") or "upload"


def process(db, job: Dict, today: Optional[date] = None) -> Dict:
    today = today or date.today()
    batch = db.select("ingest_batches", {"batch_id": job["batch_id"]})[0]
    _set_stage(db, job, "reading")
    pages = _read(job)

    _set_stage(db, job, "summarising")
    outputs = summarise.cached(db, job["doc_id"])  # content hash: a re-run costs nothing
    if outputs is None:
        outputs = summarise.summarise_pages(pages)  # ONE model call: type + brief + case fields
        impact.record("document_analyzed", len(pages), ocr_pages=sum(1 for p in pages if p.get("source") == "ocr"),
                      verified=outputs["verification"]["grounded"], engine=outputs["mode"])
    doc_type = outputs["doc_type"]

    _set_stage(db, job, "extracting")  # rules + the fields that same call returned; no second model call
    draft, engine = extraction.extract(pages, doc_type, ai_draft=outputs.get("ai_fields"), use_llm=False)
    fields, prov, low = extraction.normalise(draft, job["doc_id"], db=db)
    outputs = summarise.finish(outputs, fields, today)
    if batch["mode"] == "summary_only":
        return _summary_only(db, job, outputs, pages, today)
    case_id = job["case_id"] or f"UPL/{today.year}/{job['doc_id'][:8].upper()}"
    case, provenance, source = _merge(store.get_case(case_id, db=db), case_id, fields, prov)
    case["documents"] = sorted(set(case.get("documents") or []) | {job["doc_id"]})
    case.setdefault("doc_type", doc_type)
    case["review_fields_extra"] = [f for f in low if case.get(f) in (None, "")]

    versions = db.count("document_analyses", {"doc_id": job["doc_id"]})
    db.insert("document_analyses", [{"doc_id": job["doc_id"], "version": versions + 1, "engine": outputs["mode"],
                                     "analysis": outputs, "verified": outputs["verification"]["grounded"]}])
    db.update("documents", {"doc_id": job["doc_id"]}, {
        "case_id": case_id, "doc_type": doc_type, "pages": len(pages), "status": "processed", "analysis": outputs,
        "ocr_pages": sum(1 for p in pages if p.get("source") == "ocr")})
    conflicts = []
    if len(case["documents"]) > 1:
        conflicts = _apply_case_merge(db, case, provenance)["conflicts"]
    scored = intake.save_case(db, case, provenance, source, today)
    slot = None
    if scored["band"] == "Critical" or "UNDERTRIAL_RELEASE_ELIGIBLE" in scored["flags"]:
        slot = cause_list.fast_lane(db, case_id, today)  # fast lane: proposed slot in the nearest open draft list
    result = {"case_id": case_id, "doc_type": doc_type, "band": scored["band"], "score": scored["score"],
              "flags": scored["flags"], "reasons": scored["reasons"], "route": scored["recommended_route"],
              "data_quality": case["data_quality"], "review_fields": case["review_fields"],
              "brief": outputs["glance"], "label": outputs["label"], "extraction_engine": engine,
              "summary_engine": outputs["mode"], "unverified": outputs["verification"]["unverified"],
              "low_confidence_pages": outputs["low_confidence_pages"], "conflicts": conflicts,
              "proposed_slot": {k: slot[k] for k in ("cause_list_id", "day", "bench_id", "slot_start", "slot_end")} if slot else None}
    stage = "needs_review" if case["data_quality"] == "needs_review" else "proposed" if slot else "scored"
    db.update("ingest_jobs", {"job_id": job["job_id"]}, {"stage": stage, "status": "done", "case_id": case_id,
                                                        "result": result, "error": None, "updated_at": _now()})
    db.commit()
    impact.record("case_triaged", 1, source="upload")
    if "UNDERTRIAL_RELEASE_ELIGIBLE" in scored["flags"]:
        _handoff_undertrial(case, today)
    return result


def deadlines(outputs: Dict) -> list:
    """Dates a reader must act on: next hearing and court directions (from the verified analysis only)."""
    a, s = outputs["analysis"], outputs.get("structured") or {}
    out = [f"Next hearing: {s['next_hearing_date']}"] if s.get("next_hearing_date") else []
    return out + [d for d in a.get("directions_and_deadlines", [])][:4]


def _summary_only(db, job: Dict, outputs: Dict, pages, today: date) -> Dict:
    """Citizen upload in chat: summary + deadlines, stored against the document only - nothing enters the docket."""
    versions = db.count("document_analyses", {"doc_id": job["doc_id"]})
    db.insert("document_analyses", [{"doc_id": job["doc_id"], "version": versions + 1, "engine": outputs["mode"],
                                     "analysis": outputs, "verified": outputs["verification"]["grounded"]}])
    row = (db.select("documents", {"doc_id": job["doc_id"]}) or [{}])[0]
    if row.get("case_id") or row.get("status") == "processed":  # already part of a case: leave that record as it is
        pass
    else:
        db.update("documents", {"doc_id": job["doc_id"]}, {"doc_type": outputs["doc_type"], "pages": len(pages),
                                                           "status": "processed", "analysis": outputs})
    result = {"case_id": None, "doc_type": outputs["doc_type"], "plain": outputs["plain"], "glance": outputs["glance"],
              "deadlines": deadlines(outputs), "label": outputs["label"], "data_quality": "complete",
              "unverified": outputs["verification"]["unverified"]}
    db.update("ingest_jobs", {"job_id": job["job_id"]}, {"stage": "summarised", "status": "done", "result": result,
                                                        "error": None, "updated_at": _now()})
    db.commit()
    return result


def run_job_now(job_id: str) -> Optional[Dict]:
    """Process one specific queued job in this process (the chat attach button); the worker would do the same."""
    with store.connect() as db:
        now, ts = _now().isoformat(), db._ph("ts", "now")
        rows = db.query(f"UPDATE ingest_jobs SET status = 'running', attempts = attempts + 1, heartbeat_at = {ts}, "
                        f"updated_at = {ts} WHERE job_id = :id AND status = 'queued' RETURNING *",
                        {"now": now, "id": job_id}, table="ingest_jobs")
        db.commit()
        if rows:
            handle(db, rows[0])
        out = db.select("ingest_jobs", {"job_id": job_id})
    return out[0] if out else None


def _handoff_undertrial(case: Dict, today: date) -> None:
    try:
        from .agents.undertrial_watch import run_scan
        run_scan(case_ids=[case["case_id"]], today=today)
    except Exception as exc:  # the nightly watch picks it up anyway
        logger.info("undertrial hand-off skipped: %s", exc)


def handle(db, job: Dict) -> str:
    beat = _Heartbeat(job["job_id"])
    beat.start()
    try:
        result = process(db, job)
        if result.get("case_id") is None:
            return "summarised"
        return "needs_review" if result["data_quality"] == "needs_review" else "scored"
    except PermanentError as exc:
        db.rollback()
        return _fail(db, job, exc, permanent=True)
    except Exception as exc:
        logger.exception("job %s failed", job["job_id"])
        db.rollback()
        return _fail(db, job, exc, permanent=False)
    finally:
        beat.stop.set()


# ----------------------------------------------------------------------------- run loop
def run(once: bool = False, concurrency: Optional[int] = None, stop: Optional[threading.Event] = None) -> Dict:
    concurrency = max(1, concurrency or config.WORKER_CONCURRENCY)
    stop = stop or threading.Event()
    counts, lock = Counter(), threading.Lock()
    with store.connect() as db:
        run_id = db.insert("agent_runs", [{"job": "ingest_worker", "started": _now()}], returning="id")
        counts["requeued_stale"] = reclaim_stale(db)

    def loop():
        last_reclaim = time.monotonic()
        with store.connect() as db:
            while not stop.is_set():
                job = claim(db)
                if job is None:
                    if once:
                        return
                    stop.wait(config.WORKER_POLL_SECONDS)
                    if time.monotonic() - last_reclaim > 60:
                        counts["requeued_stale"] += reclaim_stale(db)
                        last_reclaim = time.monotonic()
                    continue
                outcome = handle(db, job)
                with lock:
                    counts[outcome] += 1

    threads = [threading.Thread(target=loop, name=f"worker-{i}") for i in range(concurrency)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    with store.connect() as db:
        db.update("agent_runs", {"id": run_id}, {"ended": _now(), "counts": dict(counts)})
    return dict(counts)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="NyayaVedika intake worker")
    ap.add_argument("--once", action="store_true", help="process claimable jobs, then exit")
    ap.add_argument("--concurrency", type=int, default=None)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    store.prepare_database()
    store.load_reference_into_triage()
    print(run(once=args.once, concurrency=args.concurrency))


if __name__ == "__main__":
    main()
