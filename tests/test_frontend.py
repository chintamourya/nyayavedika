"""Phase 8: staff read models, anonymous citizen access, the stdlib demo server (routes, roles, files),
string tables, route parity with server.py, and the gap-filling slot move used by the Cause list screen.
"""
import ast
import json
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import re
import sys
import tempfile
import threading
import unittest
import urllib.error
import urllib.request
from datetime import date, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import auth, cause_list, config, demo_seed, intake, staff_api, store, worker  # noqa: E402

STATIC = ROOT / "static"


class SeededDb(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        tmp = tempfile.mkdtemp()
        cls.old = (config.DATABASE_URL, config.STORAGE_DIR, config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER)
        config.DATABASE_URL, config.STORAGE_DIR = f"sqlite:///{tmp}/t.db", f"{tmp}/storage"
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER = "t-staff", "t-lawyer"
        with store.connect() as db:
            store.prepare_database(db)
            demo_seed.write(db, demo_seed.build(150, 42, date.today()))

    @classmethod
    def tearDownClass(cls):
        config.DATABASE_URL, config.STORAGE_DIR, config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER = cls.old


class StaffApiTests(SeededDb):
    def test_docket_filters(self):
        with store.connect() as db:
            all_rows = staff_api.docket(db)
            crit = staff_api.docket(db, band="Critical")
            review = staff_api.docket(db, needs_review=True)
            custody = staff_api.docket(db, custody=True)
            pending = db.count("cases", {"status": "pending"})
        self.assertEqual(all_rows["total"], pending)
        self.assertTrue(crit["rows"] and all(r["band"] == "Critical" for r in crit["rows"]))
        self.assertTrue(review["rows"] and all(r["data_quality"] == "needs_review" for r in review["rows"]))
        self.assertTrue(0 < custody["total"] < pending)
        scores = [r["score"] for r in all_rows["rows"]]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_case_drawer_and_source_page(self):
        data = (ROOT / "sample_docs" / "fir_01_theft.txt").read_bytes()
        batch = intake.create_batch([("fir.txt", data)])
        job = intake.batch_status(batch["batch_id"])["files"][0]
        worker.run_job_now(job["job_id"])
        case_id = intake.batch_status(batch["batch_id"])["files"][0]["case_id"]
        with store.connect() as db:
            d = staff_api.case_detail(db, case_id)
            page = staff_api.source_page(db, d["provenance"]["filing_date"]["doc_id"], d["provenance"]["filing_date"]["page"])
            missing = staff_api.case_detail(db, "NOPE/1")
        self.assertIsNone(missing)
        self.assertTrue(any(c["points"] == "+15" and "custody" in c["text"].lower() for c in d["priority"]["chips"]))
        self.assertEqual(len(d["glance"]), 3)
        self.assertTrue(d["timeline"] and d["timeline"][0]["page"] == 1)
        self.assertIn("14.03.2026", page["text"])  # the fact is on the cited page

    def test_alerts_sorted_by_days_over_limit(self):
        from nyayavedika.agents import undertrial_watch
        undertrial_watch.run_scan()
        with store.connect() as db:
            rows = staff_api.alerts(db)["alerts"]
        self.assertTrue(rows)
        over = [a["days_over_limit"] for a in rows]
        self.assertEqual(over, sorted(over, reverse=True))

    def test_weekly_numbers(self):
        with store.connect() as db:
            w = staff_api.weekly(db)
        self.assertEqual(set(w["longest_wait_days"]), {"Critical", "High", "Medium", "Routine"})
        self.assertIn("first_eligible_on", w["note"])

    def test_move_uses_gaps_left_by_first_fit(self):
        with store.connect() as db:
            start = date.today() + timedelta(days=(7 - date.today().weekday()) % 7 or 7)
            plan = cause_list.prepare(db, start, 5)
            cid = cause_list.save_draft(db, plan)
            listing = db.select("listings", {"cause_list_id": cid}, order="id", limit=1)[0]
            last_day = plan["calendar"][-1]["date"]
            out = cause_list.accept_slot(db, listing["case_id"], "move", "demo-staff", "staff", day=last_day)
        self.assertEqual(out["slot"]["day"], last_day)


class AnonymousCitizenTests(unittest.TestCase):
    def test_no_token_is_a_citizen_only_on_citizen_routes(self):
        p = auth.check(None, *auth.POLICY["POST /api/legal-aid"])
        self.assertEqual((p.role, p.actor), ("citizen", "anonymous-citizen"))
        with self.assertRaises(auth.AuthError) as ctx:
            auth.check(None, *auth.POLICY["GET /api/cases"])
        self.assertEqual(ctx.exception.status, 401)
        with self.assertRaises(auth.AuthError):  # a wrong token is never downgraded to anonymous
            auth.check("Bearer wrong", *auth.POLICY["POST /api/legal-aid"])
        old = config.ANONYMOUS_CITIZEN
        try:
            config.ANONYMOUS_CITIZEN = False
            with self.assertRaises(auth.AuthError):
                auth.check(None, *auth.POLICY["POST /api/legal-aid"])
        finally:
            config.ANONYMOUS_CITIZEN = old


class DevServerTests(SeededDb):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        import importlib.util
        spec = importlib.util.spec_from_file_location("dev_api", ROOT / "scripts" / "dev_api.py")
        cls.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.mod)
        cls.httpd = ThreadingHTTPServer(("127.0.0.1", 0), cls.mod.Handler)
        cls.base = f"http://127.0.0.1:{cls.httpd.server_address[1]}"
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        super().tearDownClass()

    def call(self, path, method="GET", body=None, token=None):
        req = urllib.request.Request(self.base + path, method=method, data=json.dumps(body).encode() if body is not None else None)
        if body is not None:
            req.add_header("Content-Type", "application/json")
        if token:
            req.add_header("Authorization", f"Bearer {token}")
        try:
            with urllib.request.urlopen(req) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            return e.code, dict(e.headers), e.read()

    def test_pages_and_assets(self):
        for page, marker in (("/", b"Choose your door"), ("/staff", b'id="tab-intake"'),
                             ("/advocate", b'data-advocate-tab="studio"'), ("/citizen", b'id="guideForm"')):
            status, _, body = self.call(page)
            self.assertEqual(status, 200, page)
            self.assertIn(marker, body)
            for src in re.findall(rb'(?:src|href)="(/static/[^"]+)"', body):
                self.assertEqual(self.call(src.decode())[0], 200, src)
        self.assertEqual(self.call("/static/../server.py")[0], 404)

    def test_three_portal_entry_points_and_advocate_role_gate(self):
        landing = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="/citizen"', landing)
        self.assertIn('href="/advocate"', landing)
        self.assertIn('href="/staff"', landing)
        self.assertIn("Advocate portal", landing)
        staff_js = (STATIC / "staff.js").read_text(encoding="utf-8")
        self.assertIn('location.pathname === "/advocate"', staff_js)
        self.assertIn('ROLE === "lawyer"', staff_js)
        self.assertIn('["staff", "lawyer"].includes(ROLE)', staff_js)
        self.assertIn("current token does not have the lawyer role", staff_js)
        common_js = (STATIC / "common.js").read_text(encoding="utf-8")
        self.assertIn('"/advocate": "lawyer"', common_js)
        self.assertIn('headers["X-Demo-Role"] = portalRole', common_js)

    def test_roles_over_http(self):
        self.assertEqual(self.call("/api/today")[0], 401)
        self.assertEqual(self.call("/api/today", token="t-staff")[0], 200)
        self.assertEqual(self.call("/api/docket", token="t-lawyer")[0], 403)
        self.assertEqual(json.loads(self.call("/api/whoami")[2])["actor"], "anonymous-citizen")
        status, _, body = self.call("/api/legal-aid", "POST", {"applicant": {"woman": True}, "district": "Warangal"})
        self.assertEqual((status, json.loads(body)["outcome"]), (200, "likely_eligible"))

    def test_word_download_headers(self):
        status, headers, body = self.call("/api/legal-aid/application.docx", "POST", {"applicant": {"woman": True}, "district": "Warangal"})
        self.assertEqual(status, 200)
        self.assertEqual(headers["Content-Type"], self.mod.DOCX)
        self.assertRegex(headers["Content-Disposition"], r'attachment; filename="legal_aid_application_Warangal_\d{4}-\d{2}-\d{2}\.docx"')
        self.assertTrue(body.startswith(b"PK"))

    def test_chat_hand_over_and_actions(self):
        status, _, body = self.call("/api/agent/chat", "POST", {"message": "Can I get a free lawyer? I earn 12,000 a month."})
        r = json.loads(body)
        self.assertEqual(r["actions"][0]["label"], "Download application (Word)")
        r1 = json.loads(self.call("/api/agent/chat", "POST", {"message": "Prepare next week's list.", "thread_id": None}, token="t-staff")[2])
        self.assertTrue(r1["awaiting_confirmation"])
        self.assertEqual(self.call("/api/agent/chat", "POST", {"message": "yes", "thread_id": r["thread_id"]}, token="t-staff")[0], 403)


class StaticContentTests(unittest.TestCase):
    def test_string_tables_complete(self):
        strings = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
        self.assertEqual(set(strings), {"en", "hi", "te"})
        self.assertEqual(set(strings["en"]), set(strings["hi"]))
        self.assertEqual(set(strings["en"]), set(strings["te"]))
        html = (STATIC / "citizen.html").read_text(encoding="utf-8") + (STATIC / "citizen.js").read_text(encoding="utf-8")
        used = set(re.findall(r'data-t[pa]?="([a-z_]+)"', html)) | set(re.findall(r'\bt\("([a-z_]+)"\)', html))
        self.assertFalse(used - set(strings["en"]), used - set(strings["en"]))

    def test_citizen_has_four_capabilities_and_safe_legal_research_rendering(self):
        html = (STATIC / "citizen.html").read_text(encoding="utf-8")
        script = (STATIC / "citizen.js").read_text(encoding="utf-8")
        tabs = re.findall(r'data-citizen-tab="([^"]+)"', html)
        self.assertEqual(tabs, ["legal", "summary", "problem", "rights"])
        self.assertIn('id="citizen-problem"', html)
        self.assertIn('api("/api/legal-problem/research"', script)
        self.assertIn("noToken: true", script)
        self.assertIn("officialResearchUrl(source.url)", script)
        self.assertIn("esc(point.text)", script)
        self.assertIn('catch (err)', script)

    def test_advocate_portal_has_only_studio_and_insights_and_real_operations(self):
        html = (STATIC / "advocate.html").read_text(encoding="utf-8")
        script = (STATIC / "advocate.js").read_text(encoding="utf-8")
        tabs = re.findall(r'data-advocate-tab="([^"]+)"', html)
        self.assertEqual(tabs, ["studio", "insights"])
        for operation in ("merge", "split", "reorder", "rotate", "remove", "ocr", "bookmarks", "index", "page_numbers"):
            self.assertIn(f'<option value="{operation}"', html)
        for kind in ("issues", "facts", "background", "summary"):
            self.assertIn(f'data-insight="{kind}"', html)
        self.assertIn('disabled aria-disabled="true"', html)
        self.assertIn('"/api/advocate/workspaces"', script)
        self.assertIn('"/api/advocate/documents"', script)
        self.assertIn('"/api/advocate/studio"', script)
        self.assertIn("esc(point.evidence)", script)

    def test_demo_banner_and_no_colour_only_bands(self):
        common = (STATIC / "common.js").read_text(encoding="utf-8")
        self.assertNotIn("Demo mode: synthetic data", common)  # banner intentionally removed
        self.assertIn("BAND_ICON", common)  # bands carry an icon and text, never colour alone
        for page in ("staff.js", "citizen.js"):
            self.assertIn("demoBanner()", (STATIC / page).read_text(encoding="utf-8"))

    def test_document_summary_has_progress_cancel_and_error_states(self):
        common = (STATIC / "common.js").read_text(encoding="utf-8")
        for page in ("staff.html", "citizen.html"):
            html = (STATIC / page).read_text(encoding="utf-8")
            self.assertIn('class="summary-progress hidden"', html)
            self.assertIn("data-summary-cancel", html)
            self.assertIn('role="alert"', html)
        self.assertIn("createSummaryProgress", common)
        self.assertIn("signal: opts.signal", common)
        self.assertIn("5 * 60 * 1000", common)

    def test_dev_server_routes_exist_in_server(self):
        dev = set(re.findall(r'@r\("[A-Z]+", r?"[^"]+", "([A-Z]+ /api/[^"]+)"\)', (ROOT / "scripts" / "dev_api.py").read_text(encoding="utf-8")))
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
        guards = {c.args[0].value for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "guard"}
        self.assertTrue(dev)
        self.assertEqual(dev - guards, set(), "dev_api serves a route server.py does not have")
        self.assertTrue(dev <= set(auth.POLICY))


if __name__ == "__main__":
    unittest.main()
