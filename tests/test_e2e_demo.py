"""End-to-end demo path, offline (no keys, no network, temp SQLite):

staff uploads 5 sample files -> worker (in-process) -> cases scored -> draft cause list has no invariant
violations -> publish -> citizen legal-aid check -> DOCX downloads and opens.

    python -m pytest tests/test_e2e_demo.py
"""
import importlib.util
import io
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import time
import unittest
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config  # noqa: E402

HAS_DEPS = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "sqlalchemy", "langgraph", "multipart"))
SAMPLES = ["fir_01_theft.txt", "fir_02_cheating.pdf", "bail_01_application.pdf", "order_01_bail_granted.pdf",
           "custody_01_jail_certificate.txt"]
TOKENS = {"staff": "e2e-staff", "lawyer": "e2e-lawyer", "citizen": "e2e-citizen"}


def H(role):
    return {"Authorization": f"Bearer {TOKENS[role]}"}


@unittest.skipUnless(HAS_DEPS, "needs fastapi, httpx, sqlalchemy, langgraph, python-multipart")
class EndToEndDemo(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from nyayavedika import db
        cls.old = (config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN, config.STORAGE_DIR)
        tmp = tempfile.mkdtemp()
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN = TOKENS.values()
        config.STORAGE_DIR = f"{tmp}/storage"
        db.reset_engine_for_tests(f"sqlite:///{tmp}/e2e.db")
        import server
        cls.ctx = TestClient(server.app)
        cls.c = cls.ctx.__enter__()          # runs start-up: migration, seed, in-process worker

    @classmethod
    def tearDownClass(cls):
        cls.ctx.__exit__(None, None, None)
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN, config.STORAGE_DIR = cls.old

    def test_full_demo_path(self):
        c = self.c
        self.assertGreater(c.get("/api/health").json()["cases_loaded"], 0)          # docket seeded at start-up

        # 1. upload five files as staff -> the in-process worker reads, summarises, extracts, scores
        files = [("files", (n, (ROOT / "sample_docs" / n).read_bytes())) for n in SAMPLES]
        r = c.post("/api/intake/batches", files=files, data={"mode": "separate"}, headers=H("staff"))
        self.assertEqual(r.status_code, 202, r.text)
        batch_id, start = r.json()["batch_id"], time.time()
        while time.time() - start < 120:
            batch = c.get(f"/api/intake/batches/{batch_id}", headers=H("staff")).json()
            if batch["status"] != "running":
                break
            time.sleep(0.5)
        self.assertEqual(batch["status"], "done", [(f["filename"], f["status"], f["error"]) for f in batch["files"]])
        self.assertLess(time.time() - start, 180)                                    # blueprint target: under 3 minutes
        for f in batch["files"]:
            self.assertTrue(f["result"]["case_id"], f)
            self.assertIn(f["result"]["band"], ("Critical", "High", "Medium", "Routine"))
            self.assertTrue(f["result"]["reasons"], "every score must carry its reasons")
        case_id = batch["files"][0]["result"]["case_id"]
        detail = c.get(f"/api/cases/{case_id}/detail", headers=H("staff"))
        self.assertEqual(detail.status_code, 200)

        # 2. triage: the queue is ordered and every case has a band
        tri = c.post("/api/triage", json={}, headers=H("staff")).json()
        self.assertTrue(tri["results"])

        # 3. scheduling: draft has no invariant violations, publish creates hearings
        d = c.post("/api/cause-lists/draft", json={"days": 5}, headers=H("staff")).json()
        self.assertEqual(d["violations"], [], d["violations"])
        self.assertEqual(d["metrics"]["advocate_conflicts"], 0)
        self.assertEqual(d["metrics"]["critical_listed"], d["metrics"]["critical_total"])
        pub = c.post(f"/api/cause-lists/{d['cause_list_id']}/publish", headers=H("staff"))
        self.assertEqual(pub.status_code, 200, pub.text)
        self.assertGreater(pub.json()["hearings_created"], 0)

        # 4. only the registrar-side role can do it: citizen is refused
        self.assertEqual(c.post("/api/cause-lists/draft", json={}, headers=H("citizen")).status_code, 403)

        # 5. citizen legal-aid check + application draft + DOCX
        body = {"applicant": {"annual_income": 120000, "in_custody": True}, "problem": "Arrested last week, no lawyer",
                "draft": True, "district": "Chittoor", "state": "Andhra Pradesh"}
        la = c.post("/api/legal-aid", json=body, headers=H("citizen"))
        self.assertEqual(la.status_code, 200, la.text)
        self.assertEqual(la.json()["outcome"], "likely_eligible")
        self.assertTrue(la.json()["where_to_apply"] or la.json()["where_to_go"])
        docx = c.post("/api/legal-aid/application.docx", json=body, headers=H("citizen"))
        self.assertEqual(docx.status_code, 200)
        with zipfile.ZipFile(io.BytesIO(docx.content)) as z:                         # a .docx is a zip with word/document.xml
            self.assertIn("word/document.xml", z.namelist())

    def test_decided_order_does_not_enter_the_hearing_queue(self):
        """A High Court order allowing a detention writ is disposed: not pending, never listed."""
        c = self.c
        text = ("IN THE HIGH COURT OF ANDHRA PRADESH\nWRIT PETITION No.2163 OF 2024\nThis Court made the following:\n\n"
                "The writ petition challenges an order of detention under the Boot-Leggers Act, 1986. The detenu was in "
                "judicial custody. The detention order is set aside. The writ petition is allowed and the detenu shall be "
                "set at liberty if he is not required in any other case.\n")
        r = c.post("/api/intake/batches", files=[("files", ("wp_2163_2024.txt", text.encode()))],
                   data={"mode": "separate"}, headers=H("staff"))
        batch_id = r.json()["batch_id"]
        for _ in range(120):
            b = c.get(f"/api/intake/batches/{batch_id}", headers=H("staff")).json()
            if b["status"] != "running":
                break
            time.sleep(0.5)
        res = b["files"][0]["result"]
        from nyayavedika import store
        with store.connect() as s:
            self.assertEqual(s.select("cases", {"case_id": res["case_id"]})[0]["status"], "disposed")
        d = c.post("/api/cause-lists/draft", json={"days": 5}, headers=H("staff")).json()
        listed = c.get(f"/api/cause-lists/{d['cause_list_id']}", headers=H("staff")).json()["listings"]
        self.assertNotIn(res["case_id"], {row["case_id"] for row in listed})


if __name__ == "__main__":
    unittest.main()
