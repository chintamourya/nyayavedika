"""Impact evidence reports: validation, privacy (identity never public, free text redacted), human verification,
verified-only summary, CSV export, and the public / staff split over HTTP (dev server). No keys, no network."""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401
import importlib.util
import json
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import auth, config, impact_reports as ir, store  # noqa: E402

ADVOCATE = {"role": "advocate", "full_name": "Test Advocate", "email": "advocate@example.org",
            "enrolment_number": "ts/1234/2015", "enrolment_year": 2015,
            "law_school": "Example Law College", "district": "Warangal",
            "features": ["advocate_summary"], "used_on": "real_matter", "task": "read_case_file",
            "minutes_without": 120, "minutes_with": 30, "timing_basis": "timed", "documents_handled": 3,
            "accuracy": "matched", "outcomes": ["saved_time", "found_missing_fact"], "usefulness": 5,
            "would_continue": "yes", "testimonial": "Saved my evening. Call me on 9876543210.",
            "quote_permission": "anonymous", "consent_store": True, "consent_contact": True}
CITIZEN = {"role": "citizen", "features": ["legal_aid_check"], "used_on": "real_matter",
           "outcomes": ["legal_aid_applied"], "usefulness": 4, "consent_store": True}


class Db(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.old = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{tmp}/t.db"
        self.db = store.connect()
        store.prepare_database(self.db)

    def tearDown(self):
        self.db.close()
        config.DATABASE_URL = self.old


class ValidationTests(unittest.TestCase):
    def test_professionals_must_be_checkable(self):
        self.assertEqual(ir.clean({**ADVOCATE, "enrolment_number": ""})["identity"]["enrolment_number"], "")  # optional
        with self.assertRaises(ir.ReportError):
            ir.clean({**ADVOCATE, "enrolment_number": "<script>"})                                      # checked if given
        for missing, msg in (("law_school", "law degree"), ("email", "email"), ("full_name", "full name")):
            with self.assertRaises(ir.ReportError) as cm:
                ir.clean({**ADVOCATE, missing: ""})
            self.assertIn(msg, cm.exception.message)
        with self.assertRaises(ir.ReportError):
            ir.clean({**ADVOCATE, "email": "not-an-email"})
        row = ir.clean({**ADVOCATE, "work_experience": "6 years, criminal side"})
        self.assertEqual(row["identity"]["enrolment_number"], "TS/1234/2015")
        self.assertEqual(row["identity"]["work_experience"], "6 years, criminal side")
        # removed fields are not stored even if a client sends them
        extra = ir.clean({**ADVOCATE, "bar_council": "X", "graduation_year": 2014, "court_name": "Y"})["identity"]
        self.assertFalse({"bar_council", "graduation_year", "court_name"} & set(extra))

    def test_optional_professional_details(self):
        staff = {**CITIZEN, "role": "court_staff", "full_name": "Test Clerk", "email": "clerk@example.org"}
        self.assertEqual(ir.clean(staff)["identity"]["designation"], "")      # designation optional, no court needed
        lawyer = {**ADVOCATE, "role": "legal_aid_lawyer"}
        ident = ir.clean(lawyer)["identity"]
        self.assertEqual((ident["practice_court"], ident["legal_services_authority"]), ("", ""))

    def test_citizen_needs_no_identity_but_consent_is_required(self):
        self.assertEqual(ir.clean(CITIZEN)["identity"]["email"], "")
        with self.assertRaises(ir.ReportError):
            ir.clean({**CITIZEN, "consent_store": False})
        with self.assertRaises(ir.ReportError):
            ir.clean({**CITIZEN, "website": "http://spam"})   # honeypot

    def test_free_text_is_redacted_and_times_come_in_pairs(self):
        self.assertNotIn("9876543210", ir.clean(ADVOCATE)["testimonial"])
        with self.assertRaises(ir.ReportError):
            ir.clean({**ADVOCATE, "minutes_with": ""})
        with self.assertRaises(ir.ReportError):
            ir.clean({**ADVOCATE, "outcomes": ["made_up"]})

    def test_options_carry_no_identity(self):
        text = json.dumps(ir.options())
        self.assertNotIn("@", text)
        self.assertIn("advocate", text)

    def test_rate_limit(self):
        key = "test-client-rate"
        self.assertTrue(all(ir.rate_ok(key, limit=3) for _ in range(3)))
        self.assertFalse(ir.rate_ok(key, limit=3))


class StorageTests(Db):
    def test_summary_counts_only_verified_reports(self):
        a = ir.submit(self.db, ADVOCATE)["id"]
        ir.submit(self.db, CITIZEN)
        s = ir.summary(self.db)
        self.assertEqual((s["reports"], s["verified"], s["pending"]), (2, 0, 2))
        self.assertIsNone(s["time"]["median_minutes_saved"])
        self.assertEqual(s["quotes"], [])
        ir.verify(self.db, a, "verified", "demo-staff", "Found on the Bar Council roll")
        s = ir.summary(self.db)
        self.assertEqual((s["verified"], s["verified_professionals"], s["verified_on_real_matters"]), (1, 1, 1))
        self.assertEqual((s["time"]["median_minutes_saved"], s["time"]["median_percent_saved"]), (90, 75))
        self.assertEqual(s["accuracy"]["matched"], 1)
        self.assertEqual(s["outcomes"]["found_missing_fact"], 1)
        self.assertEqual(len(s["quotes"]), 1)
        self.assertNotIn("Test Advocate", s["quotes"][0]["by"])   # anonymous quote: role only
        with self.assertRaises(ir.ReportError):
            ir.verify(self.db, a, "approved", "demo-staff")
        with self.assertRaises(ir.ReportError):
            ir.verify(self.db, 9999, "verified", "demo-staff")

    def test_export_contains_identity_and_is_formula_safe(self):
        ir.submit(self.db, {**ADVOCATE, "outcome_detail": "=HYPERLINK(1)"})
        text = ir.export_csv(self.db)
        self.assertIn("TS/1234/2015", text)
        self.assertIn("'=HYPERLINK(1)", text)


class HttpTests(Db):
    def setUp(self):
        super().setUp()
        self.old_tokens = (config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER)
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER = "t-staff-impact", "t-lawyer-impact"
        spec = importlib.util.spec_from_file_location("dev_api", ROOT / "scripts" / "dev_api.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), mod.Handler)
        self.base = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER = self.old_tokens
        super().tearDown()

    def call(self, path, method="GET", body=None, token=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as e:
            return e.code, e.read()

    def test_anyone_can_submit_only_staff_can_read_and_verify(self):
        self.assertEqual(self.call("/impact-report")[0], 200)
        self.assertEqual(self.call("/impact-report/review")[0], 200)
        self.assertEqual(self.call("/api/impact-reports/options")[0], 200)
        status, body = self.call("/api/impact-reports", "POST", ADVOCATE)
        self.assertEqual(status, 200)
        rid = json.loads(body)["id"]
        self.assertEqual(self.call("/api/impact-reports", "POST", {**CITIZEN, "consent_store": False})[0], 400)
        self.assertEqual(self.call("/api/impact-reports")[0], 401)
        self.assertEqual(self.call("/api/impact-reports", token="t-lawyer-impact")[0], 403)
        self.assertEqual(self.call("/api/impact-reports/summary", token="t-lawyer-impact")[0], 403)
        status, body = self.call("/api/impact-reports", token="t-staff-impact")
        self.assertEqual(json.loads(body)["reports"][0]["identity"]["email"], "advocate@example.org")
        self.assertEqual(self.call(f"/api/impact-reports/{rid}/verify", "POST", {"status": "verified", "note": "roll"},
                                   token="t-staff-impact")[0], 200)
        summary = json.loads(self.call("/api/impact-reports/summary", token="t-staff-impact")[1])
        self.assertEqual(summary["verified"], 1)
        self.assertNotIn("advocate@example.org", json.dumps(summary))
        self.assertEqual(self.call("/api/impact-reports/export.csv", token="t-staff-impact")[0], 200)


class PolicyTests(unittest.TestCase):
    def test_identity_routes_are_staff_only_and_submit_is_public(self):
        for key in ("GET /api/impact-reports", "GET /api/impact-reports/summary", "GET /api/impact-reports/export.csv",
                    "POST /api/impact-reports/{report_id}/verify"):
            self.assertEqual(auth.POLICY[key], (auth.STAFF,), key)
        self.assertIn("POST /api/impact-reports", auth.PUBLIC)
        self.assertNotIn("GET /api/impact-reports", auth.PUBLIC)


if __name__ == "__main__":
    unittest.main()
