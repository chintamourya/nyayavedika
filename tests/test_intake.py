"""Phase 3: batch intake, background worker, extraction pipeline, state hygiene.

Runs on stdlib sqlite3 with no keys:   python -m unittest discover -s tests
"""
import importlib.util
import io
import json
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, extraction, intake, llm, storage, store, worker  # noqa: E402

SAMPLES = ROOT / "sample_docs"
TRUTH_FIELDS = ("case_type", "stage", "filing_date", "accused_in_custody", "custody_since", "act", "section")
HAS_PYPDF = bool(importlib.util.find_spec("pypdf"))


def sample(name):
    return name, (SAMPLES / name).read_bytes()


def truth(name):
    return json.loads((SAMPLES / "ground_truth" / f"{Path(name).stem}.json").read_text(encoding="utf-8"))


class IntakeTestCase(unittest.TestCase):
    """Fresh database and storage folder per test."""

    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.old = (config.DATABASE_URL, config.STORAGE_DIR, config.DEMO_MAX_FILE_MB)
        config.DATABASE_URL, config.STORAGE_DIR = f"sqlite:///{tmp}/t.db", f"{tmp}/storage"
        store.prepare_database()

    def tearDown(self):
        config.DATABASE_URL, config.STORAGE_DIR, config.DEMO_MAX_FILE_MB = self.old

    def jobs(self, batch_id):
        return intake.batch_status(batch_id)["files"]

    def run_worker(self):
        return worker.run(once=True, concurrency=2)


class BatchValidationTests(IntakeTestCase):
    def test_six_files_is_400(self):
        files = [(f"f{i}.txt", f"FIR {i}".encode()) for i in range(6)]
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.create_batch(files)
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("up to 5 files", ctx.exception.message)

    def test_by_folder_rejects_more_than_two_files_in_one_folder(self):
        files = [(f"matter-a/file-{i}.txt", f"document {i}".encode()) for i in range(3)]
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.create_batch(files, mode="by_folder")
        self.assertEqual(ctx.exception.status, 400)
        self.assertIn("up to 2 files", ctx.exception.message)

    def test_by_folder_allows_two_files_in_each_of_several_folders(self):
        files = [(f"matter-{folder}/file-{i}.txt", f"{folder}-{i}".encode())
                 for folder in ("a", "b") for i in range(2)]
        out = intake.create_batch(files, mode="by_folder")
        self.assertEqual(sum(f["status"] == "queued" for f in out["files"]), 4)

    def test_wrong_extension_rejected_with_reason(self):
        out = intake.create_batch([sample("fir_01_theft.txt"), ("brief.docx", b"PK..")])
        by_name = {f["filename"]: f for f in out["files"]}
        self.assertEqual(by_name["brief.docx"]["status"], "rejected")
        self.assertIn(".docx is not accepted", by_name["brief.docx"]["reason"])
        self.assertEqual(len(self.jobs(out["batch_id"])), 1)
        self.assertEqual(intake.batch_status(out["batch_id"])["not_queued"][0]["filename"], "brief.docx")

    def test_images_wait_for_ocr(self):
        out = intake.create_batch([sample("fir_01_theft.txt"), ("scan.png", b"\x89PNG")])
        rejected = {f["filename"]: f for f in out["files"]}["scan.png"]
        self.assertEqual(rejected["status"], "rejected")
        self.assertIn("OCR", rejected["reason"])

    def test_pdf_over_page_limit_rejected_with_message(self):
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _ in range(config.DEMO_MAX_PAGES + 1):
            writer.add_blank_page(width=612, height=792)
        pdf = io.BytesIO()
        writer.write(pdf)
        out = intake.create_batch([sample("fir_01_theft.txt"), ("long.pdf", pdf.getvalue())])
        rejected = {f["filename"]: f for f in out["files"]}["long.pdf"]
        self.assertEqual(rejected["status"], "rejected")
        self.assertIn(f"limit is {config.DEMO_MAX_PAGES} pages", rejected["reason"])
        self.assertIn(f"Split it into files of {config.DEMO_MAX_PAGES} pages or fewer", rejected["reason"])

    def test_reupload_after_failure_is_queued_again(self):
        """A file whose job failed (or is waiting for a retry) is read again on re-upload, not called a duplicate."""
        first = intake.create_batch([("scan.pdf", b"%PDF-1.4 junk")])
        self.run_worker()
        self.assertEqual(self.jobs(first["batch_id"])[0]["status"], "failed")
        again = intake.create_batch([("scan.pdf", b"%PDF-1.4 junk")])
        self.assertEqual(again["files"][0]["status"], "queued")

    def test_all_rejected_is_400_with_reasons(self):
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.create_batch([("a.exe", b"x"), ("b.txt", b"")])
        self.assertEqual(ctx.exception.status, 400)
        self.assertEqual([f["status"] for f in ctx.exception.files], ["rejected", "rejected"])

    def test_oversize_rejected(self):
        config.DEMO_MAX_FILE_MB = 1
        out = intake.create_batch([("big.txt", b"x" * (1024 * 1024 + 10)), sample("fir_01_theft.txt")])
        self.assertIn("limit is 1 MB", out["files"][0]["reason"])

    def test_bad_mode_and_existing_case(self):
        with self.assertRaises(intake.IntakeError):
            intake.create_batch([sample("fir_01_theft.txt")], mode="merge_all")
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.create_batch([sample("fir_01_theft.txt")], mode="existing_case", case_number="NOPE/1")
        self.assertEqual(ctx.exception.status, 404)

    def test_request_is_fast_and_stores_by_hash(self):
        t = time.perf_counter()
        out = intake.create_batch([sample(n) for n in ("fir_01_theft.txt", "order_02_adjournment.txt", "custody_01_jail_certificate.txt")])
        self.assertLess(time.perf_counter() - t, 1.0)
        for f in out["files"]:
            self.assertEqual(storage.get(f["doc_id"]), (SAMPLES / f["filename"]).read_bytes())
            self.assertEqual(f["doc_id"], storage.sha256((SAMPLES / f["filename"]).read_bytes()))
        self.assertTrue(all(j["stage"] == "queued" for j in self.jobs(out["batch_id"])))


class DuplicateTests(IntakeTestCase):
    def test_duplicate_file_is_not_reprocessed(self):
        first = intake.create_batch([sample("fir_01_theft.txt")])
        self.run_worker()
        case_id = self.jobs(first["batch_id"])[0]["case_id"]
        second = intake.create_batch([sample("fir_01_theft.txt")])
        f = second["files"][0]
        self.assertEqual(f["status"], "duplicate")
        self.assertEqual(f["reason"], f"Already in the system, attached to case {case_id}")
        self.assertEqual(self.jobs(second["batch_id"]), [])
        self.assertNotIn("scored", self.run_worker())

    def test_same_file_twice_in_one_batch(self):
        out = intake.create_batch([sample("fir_01_theft.txt"), sample("fir_01_theft.txt")])
        self.assertEqual([f["status"] for f in out["files"]], ["queued", "duplicate"])


class WorkerPipelineTests(IntakeTestCase):
    def test_sample_docs_become_cases_and_accuracy_line(self):
        names = ["fir_01_theft.txt", "order_02_adjournment.txt", "custody_01_jail_certificate.txt"]
        if HAS_PYPDF:
            names += ["order_01_bail_granted.pdf", "bail_01_application.pdf"]
        out = intake.create_batch([sample(n) for n in names])
        counts = self.run_worker()
        self.assertEqual(counts.get("scored", 0) + counts.get("needs_review", 0), len(names))
        right = total = 0
        for job in self.jobs(out["batch_id"]):
            r = job["result"]
            self.assertIn(r["band"], ("Critical", "High", "Medium", "Routine"))
            self.assertTrue(r["reasons"])
            self.assertEqual(len(r["brief"]), 3)
            case = store.get_case(r["case_id"])
            self.assertEqual(case["source"], "upload")
            prov = case["field_provenance"]["filing_date"]
            self.assertEqual((prov["doc_id"], prov["page"]), (job["doc_id"], 1))
            self.assertGreaterEqual(prov["confidence"], config.EXTRACT_MIN_CONFIDENCE)
            gt = truth(job["filename"])
            for f in TRUTH_FIELDS:
                total += 1
                right += case.get(f) == gt[f]
        line = (f"Extraction accuracy: {right}/{total} fields ({100 * right / total:.0f}%) on {len(names)} sample docs "
                f"[engine={r['extraction_engine']}]")
        print("\n" + line)  # reported, not enforced yet (Phase 9 sets the bar)

    def test_missing_filing_date_needs_review_with_one_field(self):
        out = intake.create_batch([sample("petition_02_cheque_no_date.txt")])
        self.run_worker()
        job = self.jobs(out["batch_id"])[0]
        self.assertEqual(job["stage"], "needs_review")
        self.assertEqual(job["result"]["review_fields"], ["filing_date"])
        self.assertIsNotNone(job["result"]["score"])                          # still gets a provisional priority
        self.assertIn("NEEDS_REVIEW", job["result"]["flags"])
        self.assertTrue(store.queue_state(job["case_id"])["needs_review"])
        self.assertIsNone(store.get_case(job["case_id"]).get("filing_date"))  # never guessed

    def test_pasted_text_and_folder_case_number(self):
        text = (SAMPLES / "fir_01_theft.txt").read_text(encoding="utf-8")
        out = intake.create_batch([sample("order_02_adjournment.txt")], text=text,
                                  relative_paths=["SC-88-2024/order_02_adjournment.txt"])
        self.run_worker()
        jobs = {j["filename"]: j for j in self.jobs(out["batch_id"])}
        self.assertEqual(jobs["order_02_adjournment.txt"]["case_id"], "SC-88-2024")
        self.assertEqual(jobs["pasted_text.txt"]["stage"], "scored")

    def test_one_case_mode_merges_files(self):
        out = intake.create_batch([sample("fir_01_theft.txt"), sample("petition_02_cheque_no_date.txt")],
                                  mode="one_case", case_number="DEMO/1/2026")
        self.run_worker()
        self.assertEqual({j["case_id"] for j in self.jobs(out["batch_id"])}, {"DEMO/1/2026"})
        case = store.get_case("DEMO/1/2026")
        self.assertEqual(len(case["documents"]), 2)
        self.assertEqual(case["filing_date"], "2026-03-14")  # filled by the FIR; the petition had none

    def test_existing_case_attach_rescores(self):
        store.upsert_case({"case_id": "SC/2024/9", "case_type": "criminal_trial", "filing_date": "2024-07-11",
                           "stage": "evidence"}, source="csv")
        out = intake.create_batch([sample("order_02_adjournment.txt")], mode="existing_case", case_number="SC/2024/9")
        self.run_worker()
        case = store.get_case("SC/2024/9")
        self.assertEqual((case["source"], case["accused_in_custody"], case["custody_since"]), ("csv", True, "2024-05-02"))
        self.assertEqual(self.jobs(out["batch_id"])[0]["case_id"], "SC/2024/9")

    @unittest.skipIf(HAS_PYPDF, "pypdf installed: the PDF is readable here")
    def test_unreadable_file_fails_at_once_with_reason(self):
        out = intake.create_batch([sample("fir_02_cheating.pdf")])
        self.assertEqual(self.run_worker().get("failed"), 1)
        job = self.jobs(out["batch_id"])[0]
        self.assertEqual((job["stage"], job["attempts"]), ("failed", 1))
        self.assertIn("Could not read the file", job["error"])

    def test_bad_image_fails_at_once(self):
        out = intake.create_batch([("scan.pdf", b"%PDF-1.4 not really a pdf")])
        self.run_worker()
        job = self.jobs(out["batch_id"])[0]
        self.assertEqual((job["status"], job["attempts"]), ("failed", 1))


class QueueTests(IntakeTestCase):
    def test_stale_heartbeat_is_picked_up_again(self):
        """Kill-and-restart: a job claimed by a worker that died is requeued and finished by the next one."""
        out = intake.create_batch([sample("fir_01_theft.txt")])
        with store.connect() as db:
            job = worker.claim(db)
            self.assertEqual((job["status"], job["attempts"]), ("running", 1))
            db.update("ingest_jobs", {"job_id": job["job_id"]},
                      {"heartbeat_at": datetime.now(timezone.utc) - timedelta(minutes=config.WORKER_STALE_MINUTES + 1)})
        counts = self.run_worker()
        self.assertEqual((counts["requeued_stale"], counts.get("scored")), (1, 1))
        j = self.jobs(out["batch_id"])[0]
        self.assertEqual((j["status"], j["attempts"]), ("done", 2))

    def test_live_job_is_not_stolen(self):
        intake.create_batch([sample("fir_01_theft.txt")])
        with store.connect() as db:
            worker.claim(db)
        counts = self.run_worker()
        self.assertEqual((counts["requeued_stale"], counts.get("scored")), (0, None))

    def test_three_tries_with_growing_delay_then_failed(self):
        out = intake.create_batch([sample("fir_01_theft.txt")])
        delays = []
        with mock.patch.object(worker, "process", side_effect=RuntimeError("LLM rate limit")):
            for attempt in (1, 2, 3):
                before = datetime.now(timezone.utc)
                self.run_worker()
                j = store.connect().select("ingest_jobs", {"batch_id": out["batch_id"]})[0]
                self.assertEqual(j["attempts"], attempt)
                if attempt < 3:
                    self.assertEqual(j["status"], "queued")
                    self.assertIn("Retrying", j["error"])
                    delays.append((datetime.fromisoformat(j["available_at"]) - before).total_seconds())
                    with store.connect() as db:  # skip the wait
                        db.update("ingest_jobs", {"job_id": j["job_id"]}, {"available_at": before})
        self.assertEqual((j["status"], j["stage"]), ("failed", "failed"))
        self.assertIn("LLM rate limit", j["error"])
        self.assertGreater(delays[1], delays[0])

    def test_retry_requeues_failed_job(self):
        out = intake.create_batch([("scan.pdf", b"%PDF-1.4 junk")])
        self.run_worker()
        job_id = self.jobs(out["batch_id"])[0]["job_id"]
        self.assertEqual(intake.retry_job(out["batch_id"], job_id)["status"], "queued")
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.retry_job(out["batch_id"], job_id)
        self.assertEqual(ctx.exception.status, 409)


class CorrectionTests(IntakeTestCase):
    def _needs_review_case(self):
        out = intake.create_batch([sample("petition_02_cheque_no_date.txt")])
        self.run_worker()
        return self.jobs(out["batch_id"])[0]["case_id"]

    def test_patch_rescores_and_audits(self):
        case_id = self._needs_review_case()
        out = intake.patch_case(case_id, {"filing_date": "10.01.2026"}, "demo-staff", "staff")
        self.assertEqual((out["data_quality"], out["review_fields"]), ("complete", []))
        with store.connect() as db:
            self.assertEqual(db.count("triage_scores", {"case_id": case_id}), 2)
            audit = db.select("audit_log", {"action": "case_edit"})[0]
            self.assertFalse(db.select("case_queue_state", {"case_id": case_id})[0]["needs_review"])
        self.assertEqual(audit["detail"]["before"], {"filing_date": None})
        self.assertEqual(audit["detail"]["after"], {"filing_date": "2026-01-10"})
        self.assertEqual(store.get_case(case_id)["field_provenance"]["filing_date"]["source"], "staff")

    def test_patch_act_section_takes_maximum_from_statute_ref(self):
        store.upsert_case({"case_id": "X/1", "case_type": "criminal_trial", "filing_date": "2025-01-01", "stage": "charge",
                           "accused_in_custody": False}, source="csv")
        intake.patch_case("X/1", {"act": "BNS", "section": "309"}, "demo-staff", "staff")
        self.assertEqual(store.get_case("X/1")["max_sentence_years"], 14)

    def test_patch_validation(self):
        case_id = self._needs_review_case()
        for changes, status in (({"score": 99}, 400), ({"filing_date": "soon"}, 400), ({"stage": "trial"}, 400)):
            with self.assertRaises(intake.IntakeError) as ctx:
                intake.patch_case(case_id, changes, "demo-staff", "staff")
            self.assertEqual(ctx.exception.status, status)
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.patch_case("NOPE", {"stage": "evidence"}, "demo-staff", "staff")
        self.assertEqual(ctx.exception.status, 404)


class StructuredRowTests(IntakeTestCase):
    CSV = ("case_id,case_type,filing_date,stage,accused_in_custody,custody_since,max_sentence_years,advocate_ids\n"
           "CC/2025/1,cheque_bounce,2025-02-01,evidence,,,,ADV-01;ADV-02\n"
           "SC/2023/7,criminal_trial,2023-05-05,evidence,true,2023-04-01,7,ADV-03\n"
           "OS/2019/3,civil_suit,2019-09-09,arguments,,,,\n")

    def test_csv_rows_load_as_cases(self):
        out = intake.load_rows("docket.csv", self.CSV.encode())
        self.assertEqual(out["loaded"], 3)
        case = store.get_case("SC/2023/7")
        self.assertEqual((case["source"], case["accused_in_custody"], case["advocate_ids"]), ("csv", True, ["ADV-03"]))

    def test_json_and_caps(self):
        self.assertEqual(intake.load_rows("d.json", json.dumps([{"case_id": "W/1", "case_type": "writ"}]).encode())["loaded"], 1)
        rows = [{"case_id": f"R/{i}", "case_type": "writ"} for i in range(6)]
        for data, name in ((json.dumps(rows), "d.json"), (json.dumps([{"case_type": "writ"}]), "d.json"), ("x", "d.xlsx")):
            with self.assertRaises(intake.IntakeError) as ctx:
                intake.load_rows(name, data.encode())
            self.assertEqual(ctx.exception.status, 400)


class ExtractionRuleTests(unittest.TestCase):
    def tearDown(self):
        llm.set_backend(None)

    def test_unknown_custody_is_possible_custody(self):
        base = {"case_id": "U1", "case_type": "criminal_trial", "filing_date": "2026-01-01", "stage": "charge"}
        unknown = extraction.provisional_score(base, date(2026, 10, 26))
        known_free = extraction.provisional_score({**base, "accused_in_custody": False}, date(2026, 10, 26))
        self.assertIn("CUSTODY_UNKNOWN", unknown["flags"])
        self.assertEqual(unknown["score"], known_free["score"] + 15)

    def test_low_confidence_value_not_used(self):
        draft = extraction.CaseDraft(case_type=extraction.DraftField(value="bail", confidence=0.3, page=1))
        fields, prov, review = extraction.normalise(draft, "doc")
        self.assertNotIn("case_type", fields)
        self.assertEqual((review, prov["case_type"]["candidate"]), (["case_type"], "bail"))

    def test_llm_values_must_be_in_the_source(self):
        class Backend:
            def structured(self, model, system, messages, schema):
                return {"filing_date": {"value": "2026-03-01", "confidence": 0.99, "page": 1},   # invented
                        "section": {"value": "379", "confidence": 0.99, "page": 1},              # invented
                        "custody_since": {"value": "15.03.2026", "confidence": 0.95, "page": 1}}  # real
        llm.set_backend(Backend())
        pages = [{"page": 1, "text": (SAMPLES / "fir_01_theft.txt").read_text(encoding="utf-8")}]
        draft, engine = extraction.extract(pages)
        self.assertEqual(engine, "llm+rules")
        self.assertEqual(draft.filing_date.value, "2026-03-14")   # the rules value survives; the invented one is dropped
        self.assertEqual(draft.section.value, "303(2)")
        self.assertEqual(draft.custody_since.value, "2026-03-15")


class StateHygieneTests(IntakeTestCase):
    def test_no_bytes_dict_and_no_text_in_state(self):
        from nyayavedika.agents import document_analyst as da
        self.assertFalse(hasattr(da, "_BLOBS") or hasattr(da, "register_upload"))
        self.assertTrue({"text", "pages", "parts"}.isdisjoint(da.DocState.__annotations__))
        key = storage.put((SAMPLES / "fir_01_theft.txt").read_bytes())
        state = {"doc_id": key, "filename": "fir.txt", "language": "English"}
        for node in (da.ocr_node, da.plan_node, da.synthesize_node):
            update = node(state)
            self.assertTrue({"text", "pages", "parts"}.isdisjoint(update), node.__name__)
            state.update(update)
        self.assertEqual(state["analysis"]["engine"], "heuristic")


@unittest.skipUnless(all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "sqlalchemy", "langgraph", "multipart")),
                     "fastapi / httpx / sqlalchemy / langgraph / python-multipart not installed")
class IntakeApiTests(IntakeTestCase):
    def setUp(self):
        super().setUp()
        from fastapi.testclient import TestClient
        import server
        self.old_token = config.DEMO_TOKEN_STAFF
        config.DEMO_TOKEN_STAFF = "t-staff"
        self.client, self.h = TestClient(server.app), {"Authorization": "Bearer t-staff"}

    def tearDown(self):
        config.DEMO_TOKEN_STAFF = self.old_token
        super().tearDown()

    def test_upload_flow(self):
        files = [("files", (n, (SAMPLES / n).read_bytes(), "text/plain"))
                 for n in ("fir_01_theft.txt", "order_02_adjournment.txt", "custody_01_jail_certificate.txt")]
        r = self.client.post("/api/intake/batches", files=files, data={"mode": "separate"}, headers=self.h)
        self.assertEqual(r.status_code, 202)
        worker.run(once=True)
        status = self.client.get(f"/api/intake/batches/{r.json()['batch_id']}", headers=self.h).json()
        self.assertEqual([f["stage"] for f in status["files"]], ["scored", "scored", "proposed"])
        self.assertIsNotNone(status["files"][2]["result"]["proposed_slot"])
        six = [("files", (f"f{i}.txt", b"FIR", "text/plain")) for i in range(6)]
        self.assertEqual(self.client.post("/api/intake/batches", files=six, headers=self.h).status_code, 400)


if __name__ == "__main__":
    unittest.main()
