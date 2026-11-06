"""Files and folders: what happens when staff or a citizen hand the system one file, several files, or a folder.

Regression tests for the intake flow (nyayavedika.intake + nyayavedika.worker + the attach button of the chat):
  * a folder is not silently merged into one case;
  * junk files do not count and do not fail a batch;
  * a file that is already in the system is still summarised for a citizen, and is never reported as "unreadable";
  * jobs that write the same case never run at the same time;
  * a failed file can be sent again.
Runs offline on SQLite:   python -m unittest tests.test_file_flow
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, intake, storage, store, worker  # noqa: E402

SAMPLES = ROOT / "sample_docs"


def sample(name, rel=None):
    return (name, (SAMPLES / name).read_bytes()), rel


def batch(names, mode="separate", rels=None, **kw):
    files = [(n, (SAMPLES / n).read_bytes()) for n in names]
    return intake.create_batch(files, mode, relative_paths=rels, **kw)


_OLD_INLINE = config.INLINE_WORKER


def setUpModule():       # scoped to this module: a global setting at import would leak into the other test files
    config.INLINE_WORKER = False


def tearDownModule():
    config.INLINE_WORKER = _OLD_INLINE


class FileFlowCase(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.old = (config.DATABASE_URL, config.STORAGE_DIR)
        config.DATABASE_URL, config.STORAGE_DIR = f"sqlite:///{tmp}/t.db", f"{tmp}/storage"
        store.prepare_database()

    def tearDown(self):
        config.DATABASE_URL, config.STORAGE_DIR = self.old

    def jobs(self, out):
        return intake.batch_status(out["batch_id"])["files"]

    def run_all(self):
        return worker.run(once=True, concurrency=2)


class FolderTests(FileFlowCase):
    NAMES = ["fir_01_theft.txt", "order_02_adjournment.txt", "petition_02_cheque_no_date.txt"]

    def test_plain_folder_does_not_merge_separate_files_into_one_case(self):
        names = self.NAMES[:config.MAX_FILES_PER_FOLDER]   # a folder holds at most MAX_FILES_PER_FOLDER files
        out = batch(names, rels=[f"My papers/{n}" for n in names])
        self.assertEqual([f["case_id"] for f in out["files"]], [None] * len(names))
        self.run_all()
        cases = {j["case_id"] for j in self.jobs(out)}
        self.assertEqual(len(cases), len(names))
        self.assertNotIn("My papers", cases)          # a folder name is not a case number

    def test_folder_named_like_a_case_number_keeps_its_files_together(self):
        out = batch(self.NAMES[:2], rels=[f"SC-88-2024/{n}" for n in self.NAMES[:2]])
        self.assertEqual({f["case_id"] for f in out["files"]}, {"SC-88-2024"})
        self.run_all()
        self.assertEqual(len(store.get_case("SC-88-2024")["documents"]), 2)

    def test_by_folder_makes_one_case_per_folder(self):
        rels = ["Rahul/fir_01_theft.txt", "Rahul/order_02_adjournment.txt", "Meena/petition_02_cheque_no_date.txt"]
        out = batch(self.NAMES, mode="by_folder", rels=rels)
        ids = [f["case_id"] for f in out["files"]]
        self.assertEqual(ids[0], ids[1])
        self.assertNotEqual(ids[0], ids[2])
        self.assertTrue(all(i.startswith("UPL/") for i in ids))
        self.assertFalse(any("Rahul" in i or "Meena" in i for i in ids))   # no names from a path end up in a case id
        self.run_all()
        self.assertEqual(len(store.get_case(ids[0])["documents"]), 2)
        self.assertEqual(len(store.get_case(ids[2])["documents"]), 1)

    def test_same_folder_in_two_batches_gets_the_same_case(self):
        a = batch(self.NAMES[:1], mode="by_folder", rels=["Rahul/fir_01_theft.txt"])
        b = batch(self.NAMES[1:2], mode="by_folder", rels=["Rahul/order_02_adjournment.txt"])
        self.assertEqual(a["files"][0]["case_id"], b["files"][0]["case_id"])

    def test_path_in_the_file_name_is_a_folder_not_part_of_the_name(self):
        out = intake.create_batch([("SC-12-2025/fir_01_theft.txt", (SAMPLES / "fir_01_theft.txt").read_bytes())])
        self.assertEqual(out["files"][0]["filename"], "fir_01_theft.txt")
        self.assertEqual(out["files"][0]["case_id"], "SC-12-2025")

    def test_junk_files_are_skipped_and_do_not_count_against_the_cap(self):
        files = [(n, (SAMPLES / n).read_bytes()) for n in ["fir_01_theft.txt", "order_02_adjournment.txt"]]
        files += [(".DS_Store", b"\0\0"), ("Thumbs.db", b"x"), ("~$draft.txt", b"x"), ("__MACOSX/._fir.txt", b"x")]
        files += [(f"extra{i}.txt", f"FIR No. {i}".encode()) for i in range(config.DEMO_MAX_FILES - 2)]
        out = intake.create_batch(files)
        by = {}
        for f in out["files"]:
            by.setdefault(f["status"], []).append(f["filename"])
        self.assertEqual(len(by["skipped"]), 4)
        self.assertEqual(len(by["queued"]), config.DEMO_MAX_FILES)

    def test_only_junk_is_not_an_error_but_nothing_is_queued(self):
        out = intake.create_batch([(".DS_Store", b"\0")])
        self.assertEqual(out["status"], "done")
        self.assertEqual(out["files"][0]["status"], "skipped")

    def test_more_than_the_cap_is_still_refused(self):
        files = [(f"f{i}.txt", f"FIR {i}".encode()) for i in range(config.DEMO_MAX_FILES + 1)]
        with self.assertRaises(intake.IntakeError) as ctx:
            intake.create_batch(files)
        self.assertEqual(ctx.exception.status, 400)


class SameCaseNeverRunsTwiceTests(FileFlowCase):
    def test_jobs_for_one_case_are_claimed_one_at_a_time(self):
        out = batch(["fir_01_theft.txt", "order_02_adjournment.txt"],          # folder cap: MAX_FILES_PER_FOLDER
                    rels=["SC-90-2024/a.txt", "SC-90-2024/b.txt"])
        with store.connect() as db:
            first = worker.claim(db)
            self.assertIsNotNone(first)
            self.assertIsNone(worker.claim(db), "a second job for the same case was handed out while the first runs")
            worker.handle(db, first)
            self.assertIsNotNone(worker.claim(db))      # once the first is done the next one is released
        self.assertEqual(len(out["files"]), 2)

    def test_separate_cases_still_run_side_by_side(self):
        batch(["fir_01_theft.txt", "order_02_adjournment.txt"])
        with store.connect() as db:
            self.assertIsNotNone(worker.claim(db))
            self.assertIsNotNone(worker.claim(db))

    def test_same_file_in_two_batches_is_not_processed_twice_at_once(self):
        first = batch(["fir_01_theft.txt"])
        second = intake.create_batch([("fir_01_theft.txt", (SAMPLES / "fir_01_theft.txt").read_bytes())], mode="summary_only")
        self.assertEqual(second["files"][0]["status"], "queued")        # a citizen summary re-uses the file
        with store.connect() as db:
            self.assertIsNotNone(worker.claim(db))
            self.assertIsNone(worker.claim(db))                         # same document: wait for the first
        self.assertEqual(first["files"][0]["doc_id"], second["files"][0]["doc_id"])


class DuplicateTests(FileFlowCase):
    def test_citizen_summary_of_a_file_already_in_the_docket(self):
        first = batch(["fir_01_theft.txt"])
        self.run_all()
        case_id = self.jobs(first)[0]["case_id"]
        again = intake.create_batch([("fir.txt", (SAMPLES / "fir_01_theft.txt").read_bytes())], mode="summary_only")
        self.assertEqual(again["files"][0]["status"], "queued")
        self.run_all()
        job = self.jobs(again)[0]
        self.assertEqual(job["status"], "done")
        self.assertIsNone(job["result"]["case_id"])                    # nothing is attached to a case for a citizen
        self.assertIn("First Information Report", job["result"]["plain"])
        doc = store.connect().select("documents", {"doc_id": job["doc_id"]})[0]
        self.assertEqual(doc["case_id"], case_id)                        # the staff's record is untouched
        self.assertEqual(doc["status"], "processed")

    def test_staff_duplicate_names_the_case_and_never_says_unreadable(self):
        first = batch(["fir_01_theft.txt"])
        self.run_all()
        second = batch(["fir_01_theft.txt"])
        f = second["files"][0]
        self.assertEqual(f["status"], "duplicate")
        self.assertEqual(f["reason"], f"Already in the system, attached to case {self.jobs(first)[0]['case_id']}")

    def test_duplicate_still_being_processed_has_a_readable_reason(self):
        batch(["fir_01_theft.txt"])
        second = batch(["fir_01_theft.txt"])
        self.assertTrue(second["files"][0]["reason"].startswith("Already in the system and still being processed"))

    def test_a_failed_file_can_be_sent_again(self):
        bad = intake.create_batch([("scan.pdf", b"%PDF-1.4 not really a pdf")])
        self.run_all()
        self.assertEqual(self.jobs(bad)[0]["status"], "failed")
        again = intake.create_batch([("scan.pdf", b"%PDF-1.4 not really a pdf")])
        self.assertEqual(again["files"][0]["status"], "queued")          # not "duplicate": the first run failed
        doc = store.connect().select("documents", {"doc_id": again["files"][0]["doc_id"]})[0]
        self.assertEqual((doc["batch_id"], doc["status"]), (again["batch_id"], "queued"))


class ChatAttachTests(FileFlowCase):
    """The chat's attach button end to end (offline front door)."""

    def setUp(self):
        super().setUp()
        from nyayavedika.agents.tools import BY_NAME
        self.tool = BY_NAME["analyze_document"]

    def test_citizen_gets_a_summary_for_each_file_and_no_case(self):
        out = intake.create_batch([(n, (SAMPLES / n).read_bytes()) for n in ("fir_01_theft.txt", "order_02_adjournment.txt")],
                                  mode="summary_only")
        before = len(store.connect().select("cases"))
        res = self.tool.run(ctx={"role": "citizen"}, batch_id=out["batch_id"])
        self.assertEqual([f["status"] for f in res["files"]], ["done", "done"])
        self.assertTrue(all(f["summary"] for f in res["files"]))
        self.assertEqual(res["actions"], [])
        self.assertEqual(len(store.connect().select("cases")), before)

    def test_waits_for_a_job_the_background_worker_is_holding(self):
        import threading
        import time
        out = intake.create_batch([("fir_01_theft.txt", (SAMPLES / "fir_01_theft.txt").read_bytes())], mode="summary_only")
        with store.connect() as db:
            job = worker.claim(db)                                       # the background worker took it ...
        self.assertIsNotNone(job)

        def finish_later():
            time.sleep(1.0)
            with store.connect() as db:
                worker.handle(db, job)
        t = threading.Thread(target=finish_later)
        t.start()
        res = self.tool.run(ctx={"role": "citizen"}, batch_id=out["batch_id"])   # ... and the chat waits for it
        t.join()
        self.assertEqual(res["files"][0]["status"], "done", res)
        self.assertTrue(res["files"][0]["summary"])

    def test_staff_duplicate_shows_the_existing_case(self):
        batch(["fir_01_theft.txt"])
        self.run_all()
        out = intake.create_batch([("fir_01_theft.txt", (SAMPLES / "fir_01_theft.txt").read_bytes())], mode="separate")
        res = self.tool.run(ctx={"role": "staff"}, batch_id=out["batch_id"])
        f = res["files"][0]
        self.assertEqual(f["status"], "duplicate")
        self.assertTrue(f["duplicate_of"])
        self.assertTrue(f["brief"])
        self.assertEqual(res["actions"][0]["label"], "Open case")

    def test_no_batch_id_gives_a_clear_message(self):
        self.assertIn("No file is attached", self.tool.run(ctx={"role": "citizen"})["error"])

    def test_front_door_reads_every_file_and_names_the_ones_it_could_not(self):
        from nyayavedika.agents.front_door import FrontDoor
        files = [("fir_01_theft.txt", (SAMPLES / "fir_01_theft.txt").read_bytes()), ("empty.txt", b""),
                 ("notes.docx", b"x")]
        out = intake.create_batch(files, mode="summary_only")
        r = FrontDoor("citizen").handle("what are these?", batch_id=out["batch_id"])["reply"]
        self.assertIn("I read 1 of 3 files", r)
        self.assertIn("empty.txt: not read - The file is empty", r)
        self.assertIn("notes.docx: not read - File type .docx is not accepted", r)
        self.assertNotIn("attached to case", r)                          # nothing internal leaks to a citizen

    def test_citizen_reply_has_dates_to_act_on(self):
        from nyayavedika.agents.front_door import FrontDoor
        out = intake.create_batch([("order.txt", (SAMPLES / "order_02_adjournment.txt").read_bytes())], mode="summary_only")
        r = FrontDoor("citizen").handle("what does this say", batch_id=out["batch_id"])["reply"]
        self.assertIn("Dates to act on: Next hearing: 2026-11-07", r)


class StorageSafetyTests(FileFlowCase):
    def test_file_names_cannot_escape_the_storage_folder(self):
        out = intake.create_batch([("../../etc/passwd.txt", b"FIR No. 1 theft")])
        f = out["files"][0]
        self.assertEqual(f["filename"], "passwd.txt")
        self.assertEqual(storage.get(f["doc_id"]), b"FIR No. 1 theft")


if __name__ == "__main__":
    unittest.main()
