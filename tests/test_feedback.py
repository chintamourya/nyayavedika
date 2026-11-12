"""Landing-page field feedback: validation, privacy (first name only, PII masked), summary numbers,
staff hide API, and the landing page's public-feedback notice and short-card / full-view markup.
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import auth, config, feedback, store  # noqa: E402

STATIC = ROOT / "static"
FULL = {
    "role": "advocate", "rating": 5, "name": "Ravi Kumar", "place": "Warangal",
    "comment": "Cause list planning saved me two wasted trips. Call me on 9876543210. Second sentence here.",
    "problem_frequency": "weekly", "people_affected": 20, "cost_types": ["travel", "lost_wages"], "days_lost": 10, "rupees_lost": 6000,
    "ease": 4, "accuracy": "mostly", "outcomes": ["saved_time"], "time_saved": "half_day", "would_recommend": "yes", "features": ["cause_list"],
}


class FeedbackTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.old = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{tmp}/fb.db"
        self.db = store.connect()
        from nyayavedika.db_schema import migrate
        migrate(self.db)
        self.db.commit()

    def tearDown(self):
        self.db.close()
        config.DATABASE_URL = self.old

    def test_only_role_and_rating_are_required(self):
        self.assertTrue(feedback.submit(self.db, {"role": "citizen", "rating": 3})["ok"])
        for bad in ({"rating": 3}, {"role": "citizen"}, {"role": "citizen", "rating": 6}, {"role": "judge", "rating": 3},
                    {"role": "citizen", "rating": 3, "cost_types": ["nonsense"]}, {"role": "citizen", "rating": 3, "days_lost": -1}):
            with self.assertRaises(feedback.FeedbackError, msg=bad) as ctx:
                feedback.submit(self.db, bad)
            self.assertEqual(ctx.exception.status, 400)

    def test_public_card_is_short_private_and_masked(self):
        feedback.submit(self.db, FULL)
        item = feedback.public(self.db)["items"][0]
        self.assertEqual(item["name"], "Ravi")                       # first name only
        self.assertEqual(item["short"], "Cause list planning saved me two wasted trips.")
        self.assertIn("[PHONE]", item["comment"])
        self.assertNotIn("9876543210", str(item))
        self.assertEqual(item["answers"]["rupees_lost"], 6000)       # full view keeps the rubric answers

    def test_headline_wins_and_long_text_is_trimmed(self):
        self.assertEqual(feedback.short_text("My headline", "ignored"), "My headline")
        out = feedback.short_text("", "word " * 100)
        self.assertLessEqual(len(out), feedback.SHORT_CHARS + 1)
        self.assertTrue(out.endswith("…"))

    def test_all_submissions_are_public_including_rating_only(self):
        feedback.submit(self.db, {"role": "citizen", "rating": 3})
        feedback.submit(self.db, {**FULL, "comment": "ok"})
        out = feedback.public(self.db)
        self.assertEqual(len(out["items"]), 2)
        rating_only = next(item for item in out["items"] if item["role"] == "citizen")
        self.assertEqual(rating_only["short"], "")
        self.assertTrue(all(item["role"] for item in out["items"]))
        self.assertEqual(out["summary"]["responses"], 2)             # still counted in the numbers

    def test_summary_numbers(self):
        feedback.submit(self.db, FULL)
        feedback.submit(self.db, {"role": "citizen", "rating": 3, "would_recommend": "no", "outcomes": ["nothing_yet"], "problem_frequency": "rarely"})
        s = feedback.public(self.db)["summary"]
        self.assertEqual((s["responses"], s["avg_rating"]), (2, 4.0))
        self.assertEqual(s["would_recommend_pct"], 50)
        self.assertEqual(s["outcome_changed_pct"], 50)
        self.assertEqual(s["face_problem_often_pct"], 50)
        self.assertEqual(s["by_role"], {"advocate": 1, "citizen": 1})

    def test_comparable_task_times_are_aggregated_and_not_public_per_person(self):
        feedback.submit(self.db, {
            "role": "lawyer", "rating": 5, "task_minutes_before": 50,
            "task_minutes_with_tool": 20, "timing_basis": "observed",
        })
        feedback.submit(self.db, {
            "role": "advocate", "rating": 4, "task_minutes_before": 30,
            "task_minutes_with_tool": 20, "timing_basis": "self_reported",
        })
        result = feedback.public(self.db)
        timing = result["summary"]["task_timing"]
        self.assertEqual(timing["paired_responses"], 2)
        self.assertIsNone(timing["median_before_minutes"])
        internal_timing = feedback.summarise(self.db.select("field_feedback"))["task_timing"]
        self.assertEqual((internal_timing["median_before_minutes"], internal_timing["median_with_tool_minutes"]), (40.0, 20.0))
        self.assertEqual(internal_timing["median_minutes_saved"], 20.0)
        self.assertEqual((timing["observed"], timing["self_reported"]), (1, 1))
        self.assertNotIn("task_minutes_before", str(result["items"]))
        for _ in range(3):
            feedback.submit(self.db, {
                "role": "lawyer", "rating": 4, "task_minutes_before": 40,
                "task_minutes_with_tool": 20, "timing_basis": "observed",
            })
        self.assertIsNotNone(feedback.public(self.db)["summary"]["task_timing"]["median_before_minutes"])

    def test_task_times_require_a_complete_pair_and_basis(self):
        with self.assertRaises(feedback.FeedbackError):
            feedback.clean({"role": "citizen", "rating": 4, "task_minutes_before": 10})
        with self.assertRaises(feedback.FeedbackError):
            feedback.clean({"role": "citizen", "rating": 4, "task_minutes_before": 10,
                            "task_minutes_with_tool": 5})

    def test_api_usage_metrics_are_grouped_without_raw_routes(self):
        from unittest.mock import patch
        from nyayavedika import impact
        self.assertEqual(impact.api_feature("/api/advocate/documents/{doc_id}/chat", door="advocate"), "document_chat")
        self.assertEqual(impact.api_feature("/api/documents/analyze"), "document_analysis")
        self.assertEqual(impact.api_feature("/api/cause-lists/draft"), "cause_list_planning")
        self.assertIsNone(impact.api_feature("/api/field-feedback"))
        with patch.object(impact, "record") as record:
            impact.record_api_usage("citizen", "legal_aid", "POST", 422, 12.5)
        record.assert_called_once_with("api_usage_citizen_legal_aid_failure", 12.5,
                                       method="POST", status_code=422, door="citizen", feature="legal_aid")

    def test_impact_summary_exposes_api_counts_and_average_latency(self):
        from unittest.mock import patch
        from nyayavedika import impact
        totals = {
            "api_usage_citizen_legal_aid_success": {"count": 3, "total": 90.0},
            "api_usage_advocate_documents_failure": {"count": 1, "total": 30.0},
            "api_usage_staff_court_operations_success": {"count": 2, "total": 80.0},
            "door_visit_citizen": {"count": 4, "total": 4.0},
        }
        reach = {"unique_browsers": 2, "by_door": {"citizen": 1, "advocate": 1, "staff": 0}}
        with patch("nyayavedika.db.event_totals", return_value=totals), \
                patch("nyayavedika.db.fetch", return_value=[]), \
                patch("nyayavedika.db.reach_totals", return_value=reach):
            summary = impact.summary()
        self.assertEqual(summary["api_usage"]["total"]["requests"], 6)
        self.assertEqual(summary["api_usage"]["total"]["successful"], 5)
        self.assertEqual(summary["api_usage"]["total"]["failed"], 1)
        self.assertEqual(summary["api_usage"]["total"]["avg_server_ms"], 33.3)
        self.assertEqual(summary["api_usage"]["by_door"]["citizen"]["features"]["legal_aid"]["requests"], 3)
        self.assertEqual(summary["api_usage"]["by_door"]["advocate"]["features"]["documents"]["failed"], 1)
        self.assertEqual(summary["api_usage"]["by_feature"]["court_operations"]["requests"], 2)
        self.assertEqual(summary["reach"], reach)
        self.assertEqual(summary["door_visits"], {
            "total": 4, "by_door": {"citizen": 4, "advocate": 0, "staff": 0}
        })

    def test_hide_removes_from_wall_but_not_from_numbers(self):
        new_id = feedback.submit(self.db, FULL)["id"]
        feedback.hide(self.db, new_id)
        out = feedback.public(self.db)
        self.assertEqual((out["items"], out["summary"]["responses"]), ([], 1))
        with self.assertRaises(feedback.FeedbackError):
            feedback.hide(self.db, 9999)

    def test_roles(self):
        self.assertIn(auth.CITIZEN, auth.POLICY["POST /api/field-feedback"])
        self.assertIn(auth.CITIZEN, auth.POLICY["GET /api/field-feedback"])
        self.assertIn(auth.CITIZEN, auth.POLICY["GET /api/field-feedback/all"])
        self.assertEqual(auth.POLICY["POST /api/field-feedback/{feedback_id}/hide"], (auth.STAFF,))

    def test_all_published_feedback_endpoint_exceeds_landing_limit(self):
        for _ in range(feedback.WALL_LIMIT + 1):
            feedback.submit(self.db, {"role": "citizen", "rating": 5})
        self.assertEqual(len(feedback.public(self.db)["items"]), feedback.WALL_LIMIT)
        all_feedback = feedback.public(self.db, limit=None)
        self.assertEqual(len(all_feedback["items"]), feedback.WALL_LIMIT + 1)


class LandingMarkupTests(unittest.TestCase):
    def test_landing_links_to_feedback_in_top_navigation_without_wall_section(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        self.assertIn('class="landing-links"', html)
        self.assertIn('href="/feedback"', html)
        self.assertIn('href="/how-it-works"', html)
        self.assertIn('href="/research-evidence"', html)
        self.assertNotIn(">Learn more<", html)
        self.assertNotIn('class="fb"', html)
        self.assertNotIn('id="fbCards"', html)
        self.assertNotIn("/static/feedback.js", html)
        self.assertLess(html.index('class="landing-links"'), html.index('<span class="logo"'))

    def test_feedback_form_is_available_on_community_page(self):
        html = (STATIC / "feedback-wall.html").read_text(encoding="utf-8")
        self.assertIn('data-open-feedback', html)
        self.assertIn('id="fbFormDialog"', html)
        self.assertIn('/static/feedback.js', html)
        js = (STATIC / "feedback.js").read_text(encoding="utf-8")
        self.assertIn("Takes under 5 minutes", js)
        self.assertIn("feedbackSubmitted", (STATIC / "feedback-wall.js").read_text(encoding="utf-8"))
        self.assertIn("api(\"/api/field-feedback\"", js)
        self.assertIn("/api/field-feedback/all", (ROOT / "server.py").read_text(encoding="utf-8"))
        self.assertIn("/api/field-feedback/all", (ROOT / "scripts" / "dev_api.py").read_text(encoding="utf-8"))
        self.assertIn("Submitting publishes your feedback on this page", js)
        self.assertNotIn('name="consent_public"', js)
        self.assertNotIn("opts in", js)
        self.assertNotIn("Hide this entry", js)
        self.assertNotIn("fbHide", js)
        common = (STATIC / "common.js").read_text(encoding="utf-8")
        self.assertIn("Activity measurement", common)
        self.assertNotIn("Allow reach measurement", common)
        self.assertNotIn("Change reach settings", common)
        self.assertNotIn("data-reach-decline", common)
        self.assertIn("X-Anonymous-Browser-ID", common)
        self.assertNotIn("not verified", common.lower())
        self.assertIn("/api/reach/", common)

    def test_feedback_wall_page_renders_api_feed(self):
        html = (STATIC / "feedback-wall.html").read_text(encoding="utf-8")
        js = (STATIC / "feedback-wall.js").read_text(encoding="utf-8")
        self.assertIn('id="wallCards"', html)
        self.assertIn('id="wallSearch"', html)
        self.assertIn('id="wallRole"', html)
        self.assertIn("/api/field-feedback/all", js)
        self.assertIn('"/feedback": "feedback-wall.html"', (ROOT / "scripts" / "dev_api.py").read_text(encoding="utf-8"))
        self.assertIn('@app.get("/feedback")', (ROOT / "server.py").read_text(encoding="utf-8"))

    def test_metrics_page_is_separate_from_staff_insights(self):
        page = (STATIC / "metrics.html").read_text(encoding="utf-8")
        script = (STATIC / "metrics.js").read_text(encoding="utf-8")
        staff = (STATIC / "staff.html").read_text(encoding="utf-8")
        self.assertIn("/api/demo/metrics", script)
        self.assertIn('href="/metrics"', (STATIC / "index.html").read_text(encoding="utf-8"))
        self.assertIn("Detailed operational metrics", (ROOT / "README.md").read_text(encoding="utf-8"))
        self.assertNotIn('data-tab="insights"', staff)
        self.assertIn("aria-labelledby=\"reachHeading\"", page)
        self.assertNotIn("pilotHeading", page)
        self.assertIn("distinct browsers", script)
        self.assertNotIn("not verified", script.lower())
        self.assertNotIn("Paired task-time reports", script)
        self.assertNotIn("Aggregate medians shown after 5 responses", script)
        self.assertIn("Aggregated activity.", script)

    def test_public_docs_routes_exist_in_both_servers(self):
        source = (ROOT / "server.py").read_text(encoding="utf-8")
        for path in ("/how-it-works", "/research-evidence"):
            self.assertIn(f'@app.get("{path}"', source)
        from scripts import dev_api
        self.assertEqual(set(dev_api.DOCS), {"/how-it-works", "/research-evidence"})
        from nyayavedika import public_docs
        for path, slug in dev_api.DOCS.items():
            page = public_docs.render_page(slug)
            self.assertIn('class="doc-content"', page)
            self.assertIn('class="theme-toggle"', page)
            self.assertIn('common.js?v=14', page)
            self.assertIn("<h1>", page)
            self.assertIn("<table>", page)
            self.assertNotIn("text/markdown", page)
            if path == "/how-it-works":
                self.assertIn("language-mermaid", page)
                self.assertIn("/static/docs.js", page)
            else:
                self.assertNotIn("/static/docs.js", page)


if __name__ == "__main__":
    unittest.main()
