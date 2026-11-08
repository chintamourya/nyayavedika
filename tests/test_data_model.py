"""Phase 2: migration, reference tables, repository, synthetic seed, sample docs, regression numbers.

Runs on Python's built-in sqlite3 (no SQLAlchemy, no keys).   python -m unittest discover -s tests
"""
import importlib.util
import json
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sqlite3
import sys
import tempfile
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, demo_seed, reference_data, sample_data, scheduler, store, triage  # noqa: E402
from nyayavedika.db_schema import SCHEMA  # noqa: E402

TODAY = date(2026, 10, 26)


def _tmp_url() -> str:
    return f"sqlite:///{tempfile.mkdtemp()}/t.db"


def _load_script(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "scripts" / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _regression_numbers():
    cases = sample_data.generate(600, seed=42, today=TODAY)
    m = scheduler.build_cause_list(triage.triage_all(cases, TODAY), TODAY, 5)["metrics"]
    b = m["baseline_fifo"]
    return (m["critical_avg_wait_days"], b["critical_avg_wait_days"], m["advocate_conflicts"], b["advocate_conflicts"],
            round(m["expected_effective_hearings"]), round(b["expected_effective_hearings"]))


# SUBMISSION.md, 600-case docket, seed 42, triage rules-v2 (rules-v1 gave 0.11 and 229; see the note there)
SUBMISSION_NUMBERS = (0.09, 1.40, 0, 275, 228, 203)


class RegressionTests(unittest.TestCase):
    def test_submission_numbers_reproduce(self):
        self.assertEqual(_regression_numbers(), SUBMISSION_NUMBERS)


class MigrationTests(unittest.TestCase):
    def test_runs_twice_and_creates_everything(self):
        url = _tmp_url()
        with store.connect(url, migrate=False) as db:   # raw: this test checks the migration's own report
            first = store.prepare_database(db)
        with store.connect(url, migrate=False) as db:
            second = store.prepare_database(db)
            self.assertTrue(set(SCHEMA) <= db.tables())
            names = {r["name"] for r in db.execute("SELECT name FROM sqlite_master WHERE type = 'index'")}
        self.assertEqual(len(first["created"]), len(SCHEMA))
        self.assertEqual((second["created"], second["columns_added"]), ([], []))
        self.assertEqual(second["reference_rows_added"],
                         {"case_type_ref": 0, "stage_ref": 0, "statute_ref": 0, "state_legal_aid_params": 0})
        expected = {i[0] for t in SCHEMA.values() for i in t["indexes"] if not i[4]}  # GIN is Postgres-only
        self.assertTrue(expected <= names, expected - names)

    def test_extends_old_tables_and_backfills(self):
        """Tables made by the old SQLAlchemy metadata (JSON-only cases) gain the new columns and promoted values."""
        url = _tmp_url()
        conn = sqlite3.connect(url.split(":///", 1)[1])
        conn.execute("CREATE TABLE cases (case_id VARCHAR(64) PRIMARY KEY, court_id VARCHAR(64), data JSON NOT NULL, "
                     "score FLOAT, band VARCHAR(16), flags JSON, route TEXT, updated_at DATETIME)")
        conn.execute("CREATE TABLE alerts (id INTEGER PRIMARY KEY, created_at DATETIME, case_id VARCHAR(64), "
                     "kind VARCHAR(48), details JSON, draft TEXT, status VARCHAR(16), decided_at DATETIME, decision_note TEXT)")
        case = {"case_id": "SC/2020/1", "case_type": "criminal_trial", "filing_date": "2020-01-01",
                "accused_in_custody": True, "custody_since": "2021-01-01", "max_sentence_years": "life"}
        conn.execute("INSERT INTO cases (case_id, court_id, data, score, band) VALUES (?, 'DEMO-DC', ?, 50, 'High')",
                     (case["case_id"], json.dumps(case)))
        conn.executemany("INSERT INTO alerts (case_id, kind, status) VALUES (?, ?, ?)",
                         [("SC/2020/1", "undertrial_release", "pending")] * 2)
        conn.commit()
        conn.close()
        with store.connect(url, migrate=False) as db:   # raw: the old tables must reach prepare_database as they are
            report = store.prepare_database(db)
            self.assertIn("cases.source", report["columns_added"])
            self.assertEqual(report["cases_backfilled"], 1)
            self.assertEqual(report["alerts_deduped"], 1)
            row = db.select("cases", {"case_id": "SC/2020/1"})[0]
            self.assertEqual((row["case_type"], row["filing_date"], row["source"]), ("criminal_trial", "2020-01-01", "synthetic"))
            self.assertTrue(row["life_or_death"])
            self.assertIsNone(row["max_sentence_years"])
            self.assertEqual(row["score"], 50)
            with self.assertRaises(sqlite3.IntegrityError):  # one open alert per case and kind
                db.insert("alerts", [{"case_id": "SC/2020/1", "kind": "undertrial_release", "status": "pending"}])


class ReferenceTableTests(unittest.TestCase):
    def tearDown(self):
        triage.reset_reference()

    def test_seed_matches_constants_and_behaviour_is_unchanged(self):
        with store.connect(_tmp_url()) as db:
            store.prepare_database(db)
            ct = {r["case_type"]: r for r in db.select("case_type_ref")}
            self.assertEqual({k: v["base_urgency"] for k, v in ct.items()}, triage._DEFAULTS["TYPE_URGENCY"])
            self.assertEqual({k: v["adr_route"] for k, v in ct.items() if v["adr_route"]}, triage._DEFAULTS["ADR_ROUTES"])
            self.assertTrue(store.load_reference_into_triage(db))
        self.assertEqual(_regression_numbers(), SUBMISSION_NUMBERS)

    def test_code_reads_the_table(self):
        case = {"case_id": "B1", "case_type": "bail", "filing_date": "2026-10-20", "stage": "admission"}
        before = triage.score_case(case, TODAY)["score"]
        with store.connect(_tmp_url()) as db:
            store.prepare_database(db)
            db.update("case_type_ref", {"case_type": "bail"}, {"base_urgency": 30})
            store.load_reference_into_triage(db)
        self.assertEqual(triage.score_case(case, TODAY)["score"], before + 6)

    def test_empty_tables_keep_constants(self):
        self.assertFalse(triage.load_reference([], []))
        self.assertEqual(triage.TYPE_URGENCY, triage._DEFAULTS["TYPE_URGENCY"])


class StatuteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.db = store.connect(_tmp_url())
        store.prepare_database(cls.db)

    @classmethod
    def tearDownClass(cls):
        cls.db.close()

    def test_rows_marked_demo(self):
        rows = self.db.select("statute_ref")
        self.assertGreaterEqual(len(rows), 40)
        self.assertTrue(all(r["note"] == reference_data.STATUTE_NOTE for r in rows))

    def test_lookup(self):
        self.assertEqual(store.statute("BNS", "303(2)", db=self.db)["max_sentence_years"], 3)
        self.assertEqual(store.statute("B.N.S.", "Sec. 318", db=self.db)["max_sentence_years"], 7)
        self.assertEqual(store.statute("NDPS", "20", db=self.db)["act"], "NDPS Act")
        self.assertTrue(store.statute("BNS", "103", db=self.db)["life_or_death"])
        self.assertIsNone(store.statute("BNS", "316", db=self.db))  # sub-sections differ a lot -> never guessed
        self.assertIsNone(store.statute("BNS", "", db=self.db))


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.db = store.connect(_tmp_url())
        store.prepare_database(self.db)

    def tearDown(self):
        self.db.close()

    def test_case_round_trip(self):
        civil = {"case_id": "OS/2020/1", "case_type": "civil_suit", "filing_date": "05.06.2020", "stage": "evidence"}
        crim = {"case_id": "SC/2024/9", "case_type": "criminal_trial", "filing_date": "2024-01-01",
                "accused_in_custody": True, "custody_since": "2023-12-20", "max_sentence_years": 7}
        scores = {c["case_id"]: triage.score_case(c, TODAY) for c in (civil, crim)}
        store.upsert_cases([civil, crim], scores, source="csv", db=self.db)
        got = store.get_case("SC/2024/9", db=self.db)
        self.assertEqual((got["custody_since"], got["source"], got["_band"]), ("2023-12-20", "csv", scores["SC/2024/9"]["band"]))
        row = self.db.select("cases", {"case_id": "OS/2020/1"})[0]
        self.assertEqual(row["filing_date"], "2020-06-05")
        self.assertIsNone(row["accused_in_custody"])  # unknown stays NULL, never False
        pending = store.pending_cases(db=self.db)
        self.assertEqual([c["case_id"] for c in pending],
                         sorted(scores, key=lambda k: scores[k]["score"], reverse=True))

    def test_queue_listing_deferral_audit_history(self):
        store.upsert_queue_state([{"case_id": "X1", "times_deferred": 2, "must_list": True}], db=self.db)
        store.upsert_queue_state([{"case_id": "X1", "times_deferred": 3}], db=self.db)
        q = store.queue_state("X1", db=self.db)
        self.assertEqual((q["times_deferred"], q["must_list"]), (3, True))
        lid = store.insert_listing(cause_list_id=1, case_id="X1", day="2026-10-27", bench_id="CR-1",
                                   slot_start="10.30", slot_end="10.40", expected_minutes=10, band="High", score=50, db=self.db)
        self.assertEqual(lid, 1)
        self.assertEqual(store.insert_deferral(case_id="X1", reason="capacity", score=50, band="High", db=self.db), 1)
        store.insert_triage_scores([triage.score_case({"case_id": "X1", "case_type": "bail"}, TODAY)], triage.RULES_VERSION, db=self.db)
        self.assertEqual(self.db.select("triage_scores")[0]["rules_version"], triage.RULES_VERSION)
        store.audit("demo-staff", "staff", "case_edit", "case:X1", {"field": "stage"}, db=self.db)
        self.assertEqual(self.db.select("audit_log")[0]["detail"], {"field": "stage"})

    def test_audit_record_writes_audit_log(self):
        from nyayavedika import audit
        from nyayavedika.auth import Principal
        old = config.DATABASE_URL
        url = _tmp_url()
        try:
            config.DATABASE_URL = url
            with store.connect() as db:
                store.prepare_database(db)
            audit.record(Principal("lawyer", "demo-lawyer"), "release_alert_approved", "alert:7")
            with store.connect() as db:
                rows = db.select("audit_log")
        finally:
            config.DATABASE_URL = old
        self.assertEqual((rows[0]["actor"], rows[0]["action"], rows[0]["entity"]), ("demo-lawyer", "release_alert_approved", "alert:7"))


class SeedTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.data = demo_seed.build(2000, 42, TODAY)

    def test_deterministic(self):
        dump = lambda d: json.dumps(d, sort_keys=True, default=str)  # noqa: E731
        self.assertEqual(dump(demo_seed.build(200, 42, TODAY)), dump(demo_seed.build(200, 42, TODAY)))
        self.assertNotEqual(dump(demo_seed.build(200, 42, TODAY)), dump(demo_seed.build(200, 7, TODAY)))

    def test_proportions(self):
        d = self.data
        self.assertEqual(len(d["cases"]), 2000)
        self.assertEqual(sum(1 for c in d["cases"] if c.get("accused_in_custody")), 100)  # 5%
        self.assertEqual(len(d["needs_review"]), 160)                                       # 8%
        self.assertEqual(len({x["case_id"] for x in d["deferrals"]}), 150)
        self.assertEqual(len(d["advocates"]), 40)
        per_adv = {}
        for link in d["case_advocates"]:
            per_adv[link["advocate_id"]] = per_adv.get(link["advocate_id"], 0) + 1
        self.assertGreaterEqual(max(per_adv.values()), 10)
        self.assertEqual((len(d["legal_aid_requests"]), len(d["dlsa_directory"]), len(d["state_legal_aid_params"])), (200, 5, 5))
        kinds = [r["kind"] for r in d["court_calendar"]]
        self.assertEqual((kinds.count("holiday"), kinds.count("judge_leave")), (3, 1))
        self.assertTrue(all(c["source"] == "synthetic" for c in d["cases"]))

    def test_sec479_cases(self):
        d, near = self.data, set(self.data["near_threshold"])
        self.assertEqual(len(near), 30)
        for cid in near:
            self.assertTrue({"UNDERTRIAL_RELEASE_ELIGIBLE", "UNDERTRIAL_NEARING_THRESHOLD"} & set(d["scores"][cid]["flags"]))
        others = [s for k, s in d["scores"].items() if k not in near]
        self.assertFalse(any("UNDERTRIAL" in f for s in others for f in s["flags"]))

    def test_needs_review_fields_missing_not_guessed(self):
        by_id = {c["case_id"]: c for c in self.data["cases"]}
        for cid, fields in self.data["needs_review"].items():
            self.assertEqual(by_id[cid]["data_quality"], "needs_review")
            for f in fields:
                self.assertNotIn(f, by_id[cid])
        self.assertEqual({f for v in self.data["needs_review"].values() for f in v}, {"stage", "custody_since"})

    def test_adjournments_derived_from_hearings(self):
        per_case = {}
        for h in self.data["hearings"]:
            per_case[h["case_id"]] = per_case.get(h["case_id"], 0) + (h["outcome"] == "adjourned")
        for c in self.data["cases"][:300]:
            self.assertEqual(c["adjournments"], per_case.get(c["case_id"], 0))
        self.assertLessEqual(max(sum(1 for h in self.data["hearings"] if h["case_id"] == c["case_id"])
                                 for c in self.data["cases"][:300]), 15)

    def test_write_twice_replaces_synthetic_only(self):
        seed = _load_script("seed_demo")
        url = _tmp_url()
        first = seed.run(300, 42, TODAY, url)
        with store.connect(url) as db:
            store.upsert_case({"case_id": "UPLOAD/1", "case_type": "bail"}, source="upload", db=db)
        second = seed.run(300, 42, TODAY, url)
        self.assertEqual(second["cases"], first["cases"] + 1)                 # the upload survived
        self.assertEqual(second["hearings"], first["hearings"])
        self.assertEqual(second["legal_aid_requests"], first["legal_aid_requests"])


@unittest.skipUnless(importlib.util.find_spec("PIL"), "Pillow not installed (needed for the scanned sample)")
class SampleDocTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.out = Path(tempfile.mkdtemp())
        cls.made = dict(_load_script("make_sample_docs").main(cls.out))

    def test_ten_files_with_ground_truth(self):
        self.assertEqual(len(self.made), 10)
        keys = {"case_type", "stage", "filing_date", "custody_since", "accused_in_custody", "act", "section"}
        for name in self.made:
            gt = json.loads((self.out / "ground_truth" / f"{Path(name).stem}.json").read_text(encoding="utf-8"))
            self.assertTrue(keys <= set(gt), name)
            self.assertIn(gt["case_type"], triage.CASE_TYPES)
            self.assertIn(gt["stage"], triage.STAGE_MINUTES)
        gts = [json.loads(p.read_text(encoding="utf-8")) for p in (self.out / "ground_truth").glob("*.json")]
        self.assertEqual(sum(1 for g in gts if g["filing_date"] is None), 1)  # the needs_review demo file
        self.assertEqual(sorted(g["doc_type"] for g in gts).count("fir"), 3)

    def test_formats(self):
        self.assertGreaterEqual(self.made["long_01_sessions_record.pdf"], 60)
        self.assertIn(b"/Image", (self.out / "fir_03_robbery_scanned.pdf").read_bytes())
        text = (self.out / "fir_01_theft.txt").read_text(encoding="utf-8")
        self.assertIn("14.03.2026", text)
        self.assertIn(b"Section 305", (self.out / "order_01_bail_granted.pdf").read_bytes())

    def test_ground_truth_statutes_exist(self):
        with store.connect(_tmp_url()) as db:
            store.prepare_database(db)
            for p in (self.out / "ground_truth").glob("*.json"):
                g = json.loads(p.read_text(encoding="utf-8"))
                if g["case_type"] in ("criminal_trial", "bail"):
                    self.assertIsNotNone(store.statute(g["act"], g["section"], db=db), p.name)


if __name__ == "__main__":
    unittest.main()
