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
import uuid
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
        for source in dict.fromkeys(r["source"] for r in all_rows["rows"]):
            scores = [r["score"] for r in all_rows["rows"] if r["source"] == source]
            self.assertEqual(scores, sorted(scores, reverse=True))

    def test_docket_shows_uploaded_cases_before_synthetic(self):
        with store.connect() as db:
            row = db.query("SELECT case_id, score, source FROM cases WHERE status = 'pending' ORDER BY score ASC LIMIT 1")[0]
            original = {"source": row["source"], "score": row["score"]}
            try:
                db.update("cases", {"case_id": row["case_id"]}, {"source": "upload", "score": -1})
                docket = staff_api.docket(db)
                sources = [case["source"] for case in docket["rows"]]
                self.assertEqual(sources[0], "upload")
                self.assertLess(sources.index("synthetic"), len(sources))
                uploaded_scores = [case["score"] for case in docket["rows"] if case["source"] != "synthetic"]
                synthetic_scores = [case["score"] for case in docket["rows"] if case["source"] == "synthetic"]
                self.assertEqual(uploaded_scores, sorted(uploaded_scores, reverse=True))
                self.assertEqual(synthetic_scores, sorted(synthetic_scores, reverse=True))
            finally:
                db.update("cases", {"case_id": row["case_id"]}, original)

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
            alert = db.select("alerts", {"kind": "undertrial_release"}, order="id DESC", limit=1)[0]
            case = db.select("cases", {"case_id": alert["case_id"]})[0]
            original_source = case["source"]
            try:
                db.update("cases", {"case_id": alert["case_id"]}, {"source": "upload"})
                rows = staff_api.alerts(db)["alerts"]
                self.assertEqual(rows[0]["case_id"], alert["case_id"])
            finally:
                db.update("cases", {"case_id": alert["case_id"]}, {"source": original_source})
        self.assertTrue(rows)
        sources = [a["source"] for a in rows]
        self.assertEqual(sources, sorted(sources, key=lambda source: source == "synthetic"))
        for source in dict.fromkeys(sources):
            over = [a["days_over_limit"] for a in rows if a["source"] == source]
            self.assertEqual(over, sorted(over, reverse=True))

    def test_legacy_alerts_receive_the_verification_checklist(self):
        from nyayavedika.agents.undertrial_watch import CHECKLIST

        with store.connect() as db:
            alert_id = db.insert("alerts", [{
                "case_id": "UT/LEGACY-CHECKLIST-TEST",
                "kind": "undertrial_release",
                "status": "pending",
                "details": {},
                "draft": "test draft",
            }], returning="id")
            db.commit()
            alert = next(row for row in staff_api.alerts(db, "all")["alerts"] if row["id"] == alert_id)

        self.assertEqual(alert["details"]["checklist"], CHECKLIST)

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

    def test_court_diary_and_saved_cause_lists_over_http(self):
        self.assertEqual(self.call("/api/hearings", token="t-lawyer")[0], 403)
        self.assertEqual(self.call("/api/hearings?start=not-a-date", token="t-staff")[0], 400)
        status, _, body = self.call("/api/cause-lists/draft", "POST", {"start_date": "2026-11-16", "days": 5}, token="t-staff")
        self.assertEqual(status, 200)
        draft = json.loads(body)
        self.assertIn("readiness", draft)
        lists = json.loads(self.call("/api/cause-lists", token="t-staff")[2])["lists"]
        self.assertIn(draft["cause_list_id"], [l["id"] for l in lists])
        view = json.loads(self.call(f"/api/cause-lists/{draft['cause_list_id']}/view", token="t-staff")[2])
        self.assertEqual(view["status"], "draft")
        self.assertEqual(self.call("/api/cause-lists/999999/view", token="t-staff")[0], 404)
        self.assertEqual(self.call(f"/api/cause-lists/{draft['cause_list_id']}/publish", "POST", {}, token="t-staff")[0], 200)
        pv = json.loads(self.call("/api/scheduling/preview?start=2026-11-23", token="t-staff")[2])
        self.assertIn("verdict", pv)
        self.assertEqual(self.call("/api/scheduling/preview", token="t-lawyer")[0], 403)
        board = json.loads(self.call("/api/hearings?start=2026-11-16&days=5", token="t-staff")[2])
        self.assertTrue(board["hearings"])
        h = board["hearings"][0]
        bad = self.call(f"/api/hearings/{h['hearing_id']}/outcome", "POST",
                        {"outcome": "adjourned", "next_date": h["hearing_date"]}, token="t-staff")
        self.assertEqual(bad[0], 400)
        ok = self.call(f"/api/hearings/{h['hearing_id']}/outcome", "POST",
                       {"outcome": "adjourned", "reason": "Witness not present", "next_date": "2026-12-21"}, token="t-staff")
        self.assertEqual((ok[0], json.loads(ok[2])["next_date"]), (200, "2026-12-21"))

    def test_dev_api_counts_public_reach_and_distinct_feature_browsers(self):
        first_id, second_id = str(uuid.uuid4()), str(uuid.uuid4())
        from nyayavedika import db

        for browser_id in (first_id, second_id):
            req = urllib.request.Request(
                self.base + "/api/reach/public",
                method="POST",
                data=json.dumps({"browser_id": browser_id}).encode(),
                headers={"Content-Type": "application/json"},
            )
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)

        before = db.browser_feature_totals()["by_door_feature"].get("citizen", {}).get("legal_aid_check", 0)
        for browser_id in (first_id, first_id):
            req = urllib.request.Request(
                self.base + "/api/legal-aid/topics",
                headers={"X-Anonymous-Browser-ID": browser_id},
            )
            with urllib.request.urlopen(req) as response:
                self.assertEqual(response.status, 200)

        self.assertEqual(db.reach_totals()["public_browsers"], 2)
        self.assertEqual(
            db.browser_feature_totals()["by_door_feature"]["citizen"]["legal_aid_check"],
            before + 1,
        )

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

    def test_superintendent_letter_downloads_in_english_hindi_and_telugu(self):
        from nyayavedika.agents import undertrial_watch
        undertrial_watch.run_scan(today=date.today())
        with store.connect() as db:
            alerts = db.select("alerts", {"kind": "undertrial_release"}, order="id DESC", limit=1)
        self.assertTrue(alerts)
        alert_id = alerts[0]["id"]

        for language in ("en", "hi", "te"):
            status, headers, body = self.call(
                f"/api/alerts/{alert_id}/superintendent.docx?language={language}", token="t-staff")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Content-Type"], self.mod.DOCX)
            self.assertRegex(headers["Content-Disposition"], rf'attachment; filename="custody_record_review_request_{language}_.+\.docx"')
            self.assertTrue(body.startswith(b"PK"))

        self.assertEqual(self.call(
            f"/api/alerts/{alert_id}/superintendent.docx?language=kn", token="t-staff")[0], 400)

    def test_chat_hand_over_and_actions(self):
        status, _, body = self.call("/api/agent/chat", "POST", {"message": "Can I get a free lawyer? I earn 12,000 a month."})
        r = json.loads(body)
        self.assertEqual(r["actions"][0]["label"], "Download application (Word)")
        r1 = json.loads(self.call("/api/agent/chat", "POST", {"message": "Prepare next week's list.", "thread_id": None}, token="t-staff")[2])
        self.assertTrue(r1["awaiting_confirmation"])
        self.assertEqual(self.call("/api/agent/chat", "POST", {"message": "yes", "thread_id": r["thread_id"]}, token="t-staff")[0], 403)


class StaticContentTests(unittest.TestCase):
    def test_advocate_and_staff_headers_link_home(self):
        advocate_html = (STATIC / "advocate.html").read_text(encoding="utf-8")
        advocate_style = (STATIC / "advocate.css").read_text(encoding="utf-8")
        staff_html = (STATIC / "staff.html").read_text(encoding="utf-8")
        staff_style = (STATIC / "styles.css").read_text(encoding="utf-8")
        self.assertIn('<a class="home-link" href="/">Home</a>', advocate_html)
        self.assertIn(".home-link {", advocate_style)
        self.assertIn('<a class="portal-home" href="/">Home</a>', staff_html)
        self.assertIn("body.staff-page > .top > .portal-home", staff_style)
        self.assertIn("styles.css?v=19", staff_html)

    def test_theme_is_light_by_default_and_manually_toggleable_on_every_page(self):
        pages = ("index.html", "citizen.html", "staff.html", "advocate.html",
                 "feedback-wall.html", "metrics.html", "classic.html")
        for filename in pages:
            html = (STATIC / filename).read_text(encoding="utf-8")
            self.assertIn('class="theme-toggle"', html, filename)
            self.assertIn('content="#0866ff"', html, filename)
            self.assertIn('common.js?v=14', html, filename)

        common = (STATIC / "common.js").read_text(encoding="utf-8")
        styles = (STATIC / "styles.css").read_text(encoding="utf-8")
        advocate_style = (STATIC / "advocate.css").read_text(encoding="utf-8")
        docs_script = (STATIC / "docs.js").read_text(encoding="utf-8")
        self.assertIn('theme === "dark" ? "dark" : "light"', common)
        self.assertIn('applyTheme(saved)', common)
        self.assertNotIn("prefers-color-scheme", styles + advocate_style + docs_script)
        self.assertIn('dataset.theme === "dark"', docs_script)

    def test_undertrial_alert_has_telugu_letter_button(self):
        script = (STATIC / "staff.js").read_text(encoding="utf-8")
        self.assertIn('data-language="te">నిర్బంధ కాల వివరాల పరిశీలన వినతి (తెలుగు)', script)

    def test_staff_portal_has_no_insights_section(self):
        html = (STATIC / "staff.html").read_text(encoding="utf-8")
        script = (STATIC / "staff.js").read_text(encoding="utf-8")
        self.assertNotIn('data-tab="insights"', html)
        self.assertNotIn('id="tab-insights"', html)
        self.assertNotIn("weeklyKpis", html)
        self.assertNotIn("loadInsights", script)
        self.assertNotIn("/api/insights/weekly", script)
        self.assertNotIn("/api/impact", script)

    def test_string_tables_complete(self):
        strings = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
        self.assertEqual(set(strings), {"en", "hi", "te"})
        self.assertEqual(set(strings["en"]), set(strings["hi"]))
        self.assertEqual(set(strings["en"]), set(strings["te"]))
        self.assertIn("summarize_result_heading", strings["en"])
        self.assertIn("summarize_reader_note", strings["en"])
        html = (STATIC / "citizen.html").read_text(encoding="utf-8") + (STATIC / "citizen.js").read_text(encoding="utf-8")
        self.assertIn("citizen.js?v=18", html)
        used = set(re.findall(r'data-t[pa]?="([a-z_]+)"', html)) | set(re.findall(r'\bt\("([a-z_]+)"\)', html))
        self.assertFalse(used - set(strings["en"]), used - set(strings["en"]))

    def test_citizen_document_summary_renders_structured_sections(self):
        html = (STATIC / "citizen.html").read_text(encoding="utf-8")
        script = (STATIC / "citizen.js").read_text(encoding="utf-8")
        style = (STATIC / "styles.css").read_text(encoding="utf-8")
        strings = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
        self.assertIn("renderDocumentSummaryDetails(result, t)", script)
        common_script = (STATIC / "common.js").read_text(encoding="utf-8")
        self.assertIn("renderDocumentSummaryDetails(result, translate)", common_script)
        self.assertIn("summary-view-timeline", common_script)
        self.assertIn("summary-view-status", style)
        self.assertIn("summary_timeline", strings["en"])
        self.assertEqual(set(strings["en"]), set(strings["hi"]))
        self.assertEqual(set(strings["en"]), set(strings["te"]))
        self.assertIn("styles.css?v=15", html)

    def test_staff_document_summary_uses_shared_structured_renderer(self):
        html = (STATIC / "staff.html").read_text(encoding="utf-8")
        script = (STATIC / "staff.js").read_text(encoding="utf-8")
        self.assertIn("renderDocumentSummaryDetails(result, (key) => summaryLabels[key] || key)", script)
        self.assertIn("summary-view-lead", script)
        self.assertIn("verification.unverified?.length", script)
        self.assertIn("result.low_confidence_pages?.length", script)
        self.assertIn("common.js?v=14", html)
        self.assertIn("staff.js?v=32", html)

    def test_staff_daily_desk_explains_the_routine_and_case_flow(self):
        html = (STATIC / "staff.html").read_text(encoding="utf-8")
        script = (STATIC / "staff.js").read_text(encoding="utf-8")
        # the first-visit guide walks the whole flow in order, then the daily custody check
        guide = html[html.index('id="staffGuide"'):html.index('id="todoList"')]
        self.assertEqual(re.findall(r'data-workflow-tab="([^"]+)"', guide), ["intake", "docket", "cause", "diary", "undertrial"])
        self.assertIn("processed cases move to the Docket", html)
        self.assertIn("Prepare a weekly draft, check it, then publish", html)
        self.assertIn('if (tab === "docket") setDocketFilters({});', script)
        self.assertIn("nyayavedika_staff_guide_seen", script)          # opens by itself only on a first visit
        self.assertLess(html.index('id="triageFocus"'), html.index('id="diaryCard"'))   # triage and scheduling lead Today
        self.assertLess(html.index('id="schedFocus"'), html.index('id="diaryCard"'))
        tabs = re.findall(r'<button class="tab[^"]*" data-tab="([^"]+)"[^>]*>([^<]+)</button>', html)
        self.assertEqual(tabs, [
            ("today", "Today"), ("intake", "1 · Intake"), ("docket", "2 · Triage (Docket)"),
            ("cause", "3 · Scheduling (Cause list)"), ("summary", "Document summary"), ("undertrial", "Undertrial"),
        ])

    def test_citizen_has_four_capabilities_and_safe_legal_research_rendering(self):
        html = (STATIC / "citizen.html").read_text(encoding="utf-8")
        script = (STATIC / "citizen.js").read_text(encoding="utf-8")
        tabs = re.findall(r'data-citizen-tab="([^"]+)"', html)
        self.assertEqual(tabs, ["legal", "summary", "problem", "rights"])
        self.assertIn('id="citizen-problem"', html)
        self.assertIn('api("/api/legal-problem/chat"', script)
        self.assertIn('id="problemChatForm"', html)
        self.assertIn('role="log"', html)
        self.assertIn("noToken: true", script)
        self.assertIn("officialResearchUrl(source.url)", script)
        self.assertIn("esc(point.text)", script)
        self.assertIn('catch (err)', script)

    def test_advocate_portal_has_only_studio_and_insights_and_real_operations(self):
        html = (STATIC / "advocate.html").read_text(encoding="utf-8")
        script = (STATIC / "advocate.js").read_text(encoding="utf-8")
        style = (STATIC / "advocate.css").read_text(encoding="utf-8")
        tabs = re.findall(r'data-advocate-tab="([^"]+)"', html)
        self.assertEqual(tabs, ["studio", "insights", "undertrial"])
        for operation in ("merge", "split", "reorder", "rotate", "remove", "ocr", "bookmarks", "index", "page_numbers"):
            self.assertIn(f'<option value="{operation}"', html)
        for kind in ("issues", "facts", "background", "summary"):
            self.assertIn(f'data-insight="{kind}"', html)
        self.assertNotIn("Multi-document insights", html)
        self.assertIn('"/api/advocate/workspaces"', script)
        self.assertIn('"/api/advocate/documents"', script)
        self.assertIn('"/api/advocate/studio"', script)
        self.assertIn("/chat`", script)
        self.assertIn("esc(point.evidence)", script)
        self.assertIn('id="insightGuidance"', html)
        self.assertIn('id="docChatForm"', html)
        self.assertIn('id="docChatMessages"', html)
        self.assertIn('accept=".pdf,.docx,.txt,.md,.csv', html)
        self.assertIn('id="demoToken" type="text"', html)
        self.assertIn('id="lawyerTokenHint" class="muted">Demo lawyer token: mourya', html)
        self.assertIn('lawyerTokenInput.value = "mourya";', script)
        self.assertIn('setToken("mourya");', script)
        self.assertIn("advocate.js?v=16", html)
        self.assertIn("advocate.css?v=13", html)
        self.assertIn(".file-list { list-style: none; padding: 0; margin: 10px 0 0; display: grid; gap: 6px; width: 100%; min-width: 0; max-width: 100%; }", style)
        self.assertIn(".auth { display: flex; align-items: center; gap: 10px; flex-wrap: wrap; min-width: 0; max-width: 100%; }", style)
        self.assertIn(".chat-status {", style)
        self.assertIn("overflow: hidden;", style)
        self.assertIn("@keyframes progress-slide { from { transform: translateX(-100%); } to { transform: translateX(430%); } }", style)
        self.assertIn("/chat/prepare", script)
        self.assertIn("evidence: false", script)
        self.assertIn('class="toolbar-more"', script)
        self.assertIn("message.sources.length", script)
        self.assertIn("s === 0 ? \" open\" : \"\"", script)
        self.assertIn('class="insight-options"', html)
        self.assertIn('maxlength="1000"', html)
        self.assertIn("slice(-5)", script)
        self.assertIn("user_guidance: userGuidance", script)
        self.assertIn("!userGuidance && insights.cache.has(key)", script)
        self.assertIn("ensureDocumentPreview()", script)
        self.assertIn('data-goto="${n}" title="${isPdfDocument()', script)
        self.assertIn("const previewUrl = URL.createObjectURL(previewBlob);", script)
        self.assertIn("preview.src = `${previewUrl}#page=${Number(chip.dataset.goto)}`;", script)
        self.assertIn('$("#insightPreview").src = "about:blank";', script)
        self.assertIn('messages: insights.chatMessages.map(({ role, content }) => ({ role, content }))', script)
        self.assertIn("showProgressStatus(", script)
        self.assertNotIn("This session: PDF operations", html)
        self.assertNotIn("Where this scores against the problem", html)
        self.assertNotIn("Measured in this session", html)
        self.assertNotIn("METRICS_KEY", script)
        # counsel decides whether to file a Sec. 479 application here; court events are recorded in the staff portal
        self.assertIn('id="advocate-undertrial"', html)
        self.assertIn('"/api/alerts/decide"', script)
        self.assertNotIn("/state`", script)

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

    def test_legal_problem_chat_has_clear_live_progress_and_responsive_composer(self):
        html = (STATIC / "citizen.html").read_text(encoding="utf-8")
        script = (STATIC / "citizen.js").read_text(encoding="utf-8")
        styles = (STATIC / "styles.css").read_text(encoding="utf-8")
        strings = json.loads((STATIC / "i18n.json").read_text(encoding="utf-8"))
        self.assertIn('data-t="problem_chat_keyboard"', html)
        self.assertIn('role="log" aria-live="polite"', html)
        self.assertIn("createProblemProgress", script)
        self.assertIn("problem-chat-spinner", styles)
        self.assertIn("@media (max-width: 600px)", styles)
        for key in ("problem_chat_working", "problem_chat_progress", "problem_chat_still_working",
                    "problem_chat_elapsed", "problem_chat_keyboard", "problem_chat_you",
                    "problem_chat_sending"):
            self.assertIn(key, strings["en"])
            self.assertIn(key, strings["hi"])
            self.assertIn(key, strings["te"])
        self.assertIn('fetch("/static/i18n.json?v=2", { cache: "no-cache" })', script)

    def test_dev_server_routes_exist_in_server(self):
        dev = set(re.findall(r'@r\("[A-Z]+", r?"[^"]+", "([A-Z]+ /api/[^"]+)"\)', (ROOT / "scripts" / "dev_api.py").read_text(encoding="utf-8")))
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
        guards = {c.args[0].value for c in ast.walk(tree) if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "guard"}
        self.assertTrue(dev)
        self.assertEqual(dev - guards, set(), "dev_api serves a route server.py does not have")
        self.assertTrue(dev <= set(auth.POLICY))


if __name__ == "__main__":
    unittest.main()
