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
    def test_landing_has_wall_form_and_time_promise(self):
        html = (STATIC / "index.html").read_text(encoding="utf-8")
        for marker in ('id="fbCards"', 'id="fbDetail"', 'id="fbFormDialog"', "under 5 min", "/static/feedback.js"):
            self.assertIn(marker, html)
        js = (STATIC / "feedback.js").read_text(encoding="utf-8")
        self.assertIn("Takes under 5 minutes", js)
        self.assertIn("Read full feedback", js)
        self.assertIn("/api/field-feedback", js)
        self.assertIn("/api/field-feedback/all", (ROOT / "server.py").read_text(encoding="utf-8"))
        self.assertIn("/api/field-feedback/all", (ROOT / "scripts" / "dev_api.py").read_text(encoding="utf-8"))
        self.assertIn("New submissions appear here automatically", js)
        self.assertIn("Submitting publishes your feedback on this page", js)
        self.assertNotIn('name="consent_public"', js)
        self.assertNotIn("opts in", js)
        self.assertNotIn("Hide this entry", js)
        self.assertNotIn("fbHide", js)

    def test_feedback_wall_page_renders_api_feed(self):
        html = (STATIC / "feedback-wall.html").read_text(encoding="utf-8")
        js = (STATIC / "feedback-wall.js").read_text(encoding="utf-8")
        self.assertIn('id="wallCards"', html)
        self.assertIn('id="wallSearch"', html)
        self.assertIn('id="wallRole"', html)
        self.assertIn("/api/field-feedback/all", js)
        self.assertIn('"/feedback": "feedback-wall.html"', (ROOT / "scripts" / "dev_api.py").read_text(encoding="utf-8"))
        self.assertIn('@app.get("/feedback")', (ROOT / "server.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
