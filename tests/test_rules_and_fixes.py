"""The explained rules (GET /api/rules), legal_info.html as a knowledge source, and the bug fixes of 5 Nov:
draft lists no longer move queue counters, Accept/Move/Hold act on the named draft, custody cases are re-scored
as days pass, bad corrections give a 400, Insights ignores fast-lane lists. stdlib sqlite3, no keys."""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import cause_list, config, demo_seed, intake, legal_aid_kb, staff_api, store, triage  # noqa: E402

TODAY = date(2026, 10, 26)
HTML = """<main><article class="kbe" id="fir_zero"><h2>Registering an FIR</h2>
<ul><li>Any police station must record it (BNSS s.173(1)).</li><li>You get a free copy &amp; it is signed.</li></ul>
<p class="meta"><strong>Law:</strong> BNSS s.173</p>
<details><summary>Official sources (checked)</summary><ul class="src"><li><a href="https://indiacode.gov.in/items/x">https://indiacode.gov.in/items/x</a>
 – s.173 text <span class="chk">checked 2026-11-01</span></li></ul></details></article>
<article class="kbe" id="blog"><h2>A blog view</h2><ul><li>Opinion.</li></ul>
<details><ul class="src"><li><a href="https://example.com/p">https://example.com/p</a> – post</li></ul></details></article></main>"""


class RulesTests(unittest.TestCase):
    def test_rules_match_the_code(self):
        r = staff_api.rules()
        self.assertEqual([b["band"] for b in r["bands"]], ["Critical", "High", "Medium", "Routine"])
        self.assertEqual(r["bands"][0]["min_score"], 60)
        self.assertEqual(r["bands"][0]["sla_days"], config.SLA_DAYS["Critical"])
        self.assertEqual(r["base_by_type"]["habeas_corpus"], triage.TYPE_URGENCY["habeas_corpus"])
        self.assertIn(f"+{triage.CUSTODY_POINTS}", [f["points"] for f in r["factors"]])
        self.assertIn("pending", r["undertrial"]["transitions"])

    def test_band_cut_offs_unchanged(self):
        self.assertEqual([triage.band_for(s) for s in (60, 59.9, 45, 30, 0)], ["Critical", "High", "High", "Medium", "Routine"])


class KbHtmlTests(unittest.TestCase):
    def test_parse_entries_sources_and_authority(self):
        e = legal_aid_kb.parse_legal_info_html(HTML)
        self.assertEqual([x["id"] for x in e], ["fir_zero", "blog"])
        self.assertEqual(e[0]["facts"][1], "You get a free copy & it is signed.")
        self.assertEqual(e[0]["sources"][0], {"url": "https://indiacode.gov.in/items/x", "note": "s.173 text", "checked": "2026-11-01"})
        chunks = legal_aid_kb.legal_info_chunks(HTML)
        self.assertEqual([c["authority"] for c in chunks], ["primary", "secondary"])
        self.assertTrue(all(isinstance(s, str) for c in chunks for s in c["sources"]))   # Pinecone-safe metadata

    def test_ingest_and_search_cite_the_official_page(self):
        tmp = Path(tempfile.mkdtemp())
        (tmp / "legal_info.html").write_text(HTML, encoding="utf-8")
        out = legal_aid_kb.ingest(None, tmp / "dump.json", html_files=(tmp / "legal_info.html",))
        self.assertEqual(out["legal_info_entries"], 2)
        hit = legal_aid_kb.search("police will not register FIR", 1, dump=tmp / "dump.json")["passages"][0]
        self.assertEqual(hit["source_url"], "https://indiacode.gov.in/items/x")
        self.assertEqual(hit["collection"], "legal_info.html")

    def test_bundled_legal_info_topics(self):
        t = legal_aid_kb.topics()
        if not t["count"]:
            self.skipTest("legal_info.html not present")
        self.assertGreaterEqual(t["count"], 20)
        self.assertTrue(all(tp["sources"] for tp in t["topics"]))


class DbFixTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.mkdtemp()
        self.old = (config.DATABASE_URL, config.STORAGE_DIR)
        config.DATABASE_URL, config.STORAGE_DIR = f"sqlite:///{tmp}/t.db", f"{tmp}/storage"
        self.db = store.connect()
        store.prepare_database(self.db)
        store.load_reference_into_triage(self.db)
        demo_seed.write(self.db, demo_seed.build(80, 42, TODAY))

    def tearDown(self):
        self.db.close()
        config.DATABASE_URL, config.STORAGE_DIR = self.old

    def test_preparing_drafts_does_not_move_counters(self):
        before = {s["case_id"]: s["consecutive_deferrals"] for s in self.db.select("case_queue_state")}
        self.db.execute("UPDATE benches SET minutes_per_day = 30")
        for _ in range(3):
            cause_list.save_draft(self.db, cause_list.prepare(self.db, TODAY, 5))
        after = {s["case_id"]: s["consecutive_deferrals"] for s in self.db.select("case_queue_state")}
        self.assertEqual(before, after)
        self.assertEqual(self.db.count("cause_lists", {"status": "draft"}), 1)   # older drafts superseded

    def test_accept_slot_acts_on_the_named_draft(self):
        cid = cause_list.save_draft(self.db, cause_list.prepare(self.db, TODAY, 5))
        lst = self.db.select("listings", {"cause_list_id": cid}, limit=1)[0]
        out = cause_list.accept_slot(self.db, lst["case_id"], "accept", "t", "staff", cause_list_id=cid)
        self.assertEqual(out["slot"]["cause_list_id"], cid)
        with self.assertRaises(ValueError):
            cause_list.accept_slot(self.db, lst["case_id"], "accept", "t", "staff", cause_list_id=cid + 99)

    def test_custody_case_is_rescored_as_days_pass(self):
        case = {"case_id": "UT/1", "case_type": "criminal_trial", "stage": "evidence", "filing_date": "2023-01-01",
                "accused_in_custody": True, "custody_since": (TODAY - timedelta(days=1270)).isoformat(),
                "max_sentence_years": 7, "first_time_offender": False, "status": "pending"}
        store.upsert_case(case, triage.score_case(case, TODAY), source="csv", db=self.db)
        self.db.commit()
        self.assertNotIn("UNDERTRIAL_RELEASE_ELIGIBLE", self.db.select("cases", {"case_id": "UT/1"})[0]["flags"])
        self.assertGreaterEqual(cause_list.rescore_custody(self.db, TODAY + timedelta(days=10)), 1)
        row = self.db.select("cases", {"case_id": "UT/1"})[0]
        self.assertIn("UNDERTRIAL_RELEASE_ELIGIBLE", row["flags"])
        self.assertEqual(row["band"], "Critical")

    def test_bad_correction_is_a_400(self):
        cid = self.db.select("cases", limit=1)[0]["case_id"]
        for change in ({"max_sentence_years": "seven"}, {"adjournments": "many"}, {"status": "lost"}):
            with self.assertRaises(intake.IntakeError) as ctx:
                intake.patch_case(cid, change, "t", "staff", db=self.db)
            self.assertEqual(ctx.exception.status, 400)
        self.assertEqual(intake._coerce("max_sentence_years", "7 years"), 7.0)

    def test_insights_skip_fast_lane_lists(self):
        cid = cause_list.save_draft(self.db, cause_list.prepare(self.db, TODAY, 5))
        self.db.insert("cause_lists", [{"court_id": "DEMO-DC", "start_date": TODAY.isoformat(), "status": "draft",
                                        "plan": {"fast_lane": True, "days": 5}, "metrics": {}}])
        self.db.commit()
        w = staff_api.weekly(self.db)
        self.assertEqual(w["latest_cause_list"], cid)
        self.assertTrue(w["vs_oldest_first"])

    def test_today_pipeline_counts(self):
        t = cause_list.today_counters(self.db, TODAY)
        self.assertEqual(t["pipeline"]["docket_pending"], self.db.count("cases", {"status": "pending"}))
        self.assertIn("alerts_waiting_decision", t["pipeline"])


if __name__ == "__main__":
    unittest.main()
