"""Phase 6: rule engine (40 scenarios), State facts with memory, where to go, urgent help, request tracking,
knowledge index (ingest + cited search), DOCX drafts. No keys, no network, stdlib sqlite3.
"""
import importlib.util
import json
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import re
import sys
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta, timezone
from io import BytesIO
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, demo_seed, legal_aid, legal_aid_kb, store  # noqa: E402
from nyayavedika.docgen import legal_aid_docx  # noqa: E402

CASES = json.loads((ROOT / "tests" / "legal_aid_cases.json").read_text(encoding="utf-8"))
HAS_PYTHON_DOCX = bool(importlib.util.find_spec("docx"))


class DbCase(unittest.TestCase):
    def setUp(self):
        self.old = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{tempfile.mkdtemp()}/t.db"
        with store.connect() as db:
            store.prepare_database(db)
            demo_seed.write(db, demo_seed.build(30, 42, date(2026, 10, 26)))

    def tearDown(self):
        config.DATABASE_URL = self.old


class RuleEngineScenarioTests(DbCase):
    def test_forty_scenarios(self):
        self.assertEqual(len(CASES), 40)
        failures = []
        for c in CASES:
            r = legal_aid.check_eligibility(c["applicant"])
            checks = [r["outcome"] == c["outcome"], r["eligible"] == (c["outcome"] == "likely_eligible")]
            if "clauses" in c:
                checks.append(sorted(g["clause"] for g in r["grounds"]) == sorted(c["clauses"]))
            if "missing" in c:
                checks.append(r["missing_facts"] == c["missing"])
            if "urgent" in c:
                checks.append([u["number"] for u in r["urgent"] or []] == c["urgent"])
            if "fallback" in c:
                checks.append(r["income_limit_fallback"] is c["fallback"] and "default, State limit not on file" in r["income_limit_note"])
            if "forum_contains" in c:
                checks.append(c["forum_contains"] in r["where_to_apply"])
            if "steps_contain" in c:
                checks.append(any(c["steps_contain"] in s for s in r["next_steps"]))
            if not all(checks):
                failures.append(f"{c['name']}: got {r['outcome']} {[g['clause'] for g in r['grounds']]} missing={r['missing_facts']}")
        self.assertEqual(failures, [], "\n".join(failures))

    def test_every_answer_has_disclaimer_documents_and_next_steps(self):
        for c in CASES:
            r = legal_aid.check_eligibility(c["applicant"])
            self.assertIn("15100", r["disclaimer"])
            self.assertTrue(r["documents_needed"] and r["next_steps"])
            self.assertIn(r["outcome_label"], legal_aid.OUTCOME_LABELS.values())

    def test_where_to_go_by_district(self):
        r = legal_aid.check_eligibility({"woman": True, "state": "Telangana", "district": "Warangal"})
        self.assertEqual(r["where_to_go"]["district"], "Warangal")
        self.assertIn("verify", r["where_to_go"]["label"].lower())  # synthetic directory row is labelled
        other = legal_aid.where_to_go("Telangana", "Nowhere")
        self.assertIn("call 15100", other["label"])

    def test_state_limit_from_table_is_labelled(self):
        r = legal_aid.check_eligibility({"annual_income": 100000, "state": "Telangana"})
        self.assertFalse(r["income_limit_fallback"])
        self.assertIn("Income limit in Telangana: Rs. 3,00,000 (demo value, not verified", r["income_limit_note"])

    def test_request_tracking_lines(self):
        self.assertEqual(legal_aid.STATUS_FLOW, ["checked", "drafted", "applied", "lawyer_assigned", "closed"])
        self.assertTrue(all(legal_aid.WHAT_NEXT[s].strip() for s in legal_aid.STATUS_FLOW))

    def test_indian_grouping(self):
        self.assertEqual([legal_aid.inr(x) for x in (999, 300000, 12345678)], ["999", "3,00,000", "1,23,45,678"])


class StateFactTests(DbCase):
    def fake_search(self, calls):
        def search(query):
            calls.append(query)
            return {"answer": "The annual income limit for free legal aid in Telangana is Rs. 3,00,000 per year.",
                    "results": [{"url": "https://tslsa.telangana.gov.in/legal-aid.html", "content": "income ceiling Rs. 3,00,000"}]}
        return search

    def test_web_value_saved_with_source_and_date_then_reused(self):
        calls = []
        fact = legal_aid.get_state_fact("Telangana", search=self.fake_search(calls))
        self.assertEqual((fact["value"], fact["source"]), (300000, "web"))
        today = datetime.now(timezone.utc).strftime("%d %b %Y")
        self.assertEqual(fact["display"], f"Income limit in Telangana: Rs. 3,00,000, checked on {today} at tslsa.telangana.gov.in")
        again = legal_aid.get_state_fact("Telangana", search=self.fake_search(calls))
        self.assertEqual((again["source"], len(calls)), ("table", 1))  # fresh row: no second search
        with store.connect() as db:
            row = db.select("state_legal_aid_params", {"state": "Telangana"})[0]
        self.assertEqual((row["synthetic"], row["source_url"]), (False, "https://tslsa.telangana.gov.in/legal-aid.html"))

    def test_stale_value_is_searched_again(self):
        old = (datetime.now(timezone.utc) - timedelta(days=config.WEB_FACT_TTL_DAYS + 5)).isoformat()
        with store.connect() as db:
            db.update("state_legal_aid_params", {"state": "Karnataka"},
                      {"verified_at": old, "synthetic": False, "source_url": "https://kslsa.kar.nic.in"})
        calls = []
        legal_aid.get_state_fact("Karnataka", search=self.fake_search(calls))
        self.assertEqual(len(calls), 1)

    def test_no_web_returns_labelled_table_value(self):
        fact = legal_aid.get_state_fact("Tamil Nadu", search=False)
        self.assertEqual(fact["value"], 300000)
        self.assertIn("not verified", fact["display"])
        self.assertIn("not on file", legal_aid.get_state_fact("Goa", search=False)["display"])

    def test_amount_parsing(self):
        self.assertEqual(legal_aid._parse_income_limit("annual income below 1.5 lakh"), 150000)
        self.assertEqual(legal_aid._parse_income_limit("court fee Rs. 500"), None)  # not about income


FIXTURE = """intro text outside any block is ignored
########https://nalsa.gov.in/lok-adalat/############
What is a Lok Adalat?
A Lok Adalat is a forum where disputes pending in court or at the pre-litigation stage are settled amicably.
There is no court fee, and the award is final and binding on the parties.
########https://nalsa.gov.in/lok-adalat/############
########https://example-law-blog.com/legal-aid############
Who Can Get a Free Lawyer?
Women, children and persons in custody can ask the District Legal Services Authority for a panel lawyer.
########https://example-law-blog.com/legal-aid############
"""


class KnowledgeIndexTests(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())
        (self.dir / "kb.txt").write_text(FIXTURE, encoding="utf-8")
        self.dump = self.dir / "dump.json"

    def test_ingest_two_blocks_with_authority_and_stable_ids(self):
        first = legal_aid_kb.ingest(self.dir, self.dump, verified="2026-10-25")
        ids1 = [c["id"] for c in json.loads(self.dump.read_text(encoding="utf-8"))]
        second = legal_aid_kb.ingest(self.dir, self.dump, verified="2026-10-25")
        ids2 = [c["id"] for c in json.loads(self.dump.read_text(encoding="utf-8"))]
        self.assertEqual((first["chunks"], first["primary"]), (2, 1))
        self.assertEqual(ids1, ids2)  # content-hash ids: re-runs are safe
        chunks = {c["source_url"]: c for c in json.loads(self.dump.read_text(encoding="utf-8"))}
        lok = chunks["https://nalsa.gov.in/lok-adalat/"]
        self.assertEqual((lok["authority"], lok["topic"], lok["heading"]), ("primary", "lok_adalat", "What is a Lok Adalat?"))
        self.assertTrue(lok["text"].startswith("What is a Lok Adalat?"))
        self.assertEqual(chunks["https://example-law-blog.com/legal-aid"]["authority"], "secondary")

    def test_search_cites_and_flags_secondary_only(self):
        legal_aid_kb.ingest(self.dir, self.dump)
        r = legal_aid_kb.search("What is a Lok Adalat?", 1, dump=self.dump)
        self.assertIn("https://nalsa.gov.in/lok-adalat/ (primary", r["passages"][0]["citation"])
        self.assertIsNone(r["secondary_only_note"])
        r2 = legal_aid_kb.search("free lawyer panel", 1, dump=self.dump)
        self.assertEqual(r2["passages"][0]["authority"], "secondary")
        self.assertIn("secondary sources", r2["secondary_only_note"])

    def test_real_file_answers_lok_adalat_with_citation(self):
        if not legal_aid_kb.DUMP.exists():
            self.skipTest("run scripts/ingest_legal_aid.py first")
        r = legal_aid_kb.search("What is a Lok Adalat?")
        self.assertTrue(r["passages"])
        self.assertTrue(r["passages"][0]["citation"].startswith("http"))
        self.assertTrue(any("lok adalat" in p["text"].lower() for p in r["passages"]))

    def test_marker_parsing_uses_url_inside_named_block(self):
        blocks = legal_aid_kb.parse_blocks("########NALSA############\nsource: https://nalsa.gov.in/legal-aid/\nText.\n########NALSA############")
        self.assertEqual((blocks[0]["source_url"], blocks[0]["authority"]), ("https://nalsa.gov.in/legal-aid/", "primary"))


def docx_text(data: bytes) -> str:
    if HAS_PYTHON_DOCX:
        import docx
        d = docx.Document(BytesIO(data))
        return "\n".join([p.text for p in d.paragraphs] + [p.text for s in d.sections for p in s.footer.paragraphs])
    z = zipfile.ZipFile(BytesIO(data))
    xml = z.read("word/document.xml").decode() + z.read("word/footer1.xml").decode()
    return re.sub(r"<[^>]+>", "", xml.replace("<w:br/>", "\n").replace("</w:p>", "\n"))


class DocxTests(DbCase):
    def test_application_docx(self):
        data = legal_aid_docx.build_application_docx({"applicant": {"woman": True, "annual_income": 90000},
                                                      "problem": "My husband threw me out of the house.",
                                                      "district": "Warangal", "state": "Telangana"})
        self.assertTrue(data.startswith(b"PK"))
        text = docx_text(data)
        self.assertIn(legal_aid_docx.APPLICATION_TITLE, text)
        self.assertIn("Warangal", text)
        self.assertIn("Information, not legal advice", text)
        self.assertIn("Name: [to be filled]", text)
        self.assertIn("[x] Section 12(c)", text)
        self.assertIn("My husband threw me out of the house.", text)  # template facts paragraph (no LLM key)
        if not HAS_PYTHON_DOCX:
            z = zipfile.ZipFile(BytesIO(data))
            self.assertIn('w:w="11906" w:h="16838"', z.read("word/document.xml").decode())  # A4

    def test_unknown_district_uses_placeholder(self):
        text = docx_text(legal_aid_docx.build_application_docx({"applicant": {}, "problem": ""}))
        self.assertIn("District Legal Services Authority, [to be filled]", text)
        self.assertIn("[to be filled]", text)

    def test_release_docx(self):
        alert = {"case_id": "SC/2023/1", "draft": "", "details": {
            "custody_since": "2023-01-12", "release_check": {"custody_days": 1383, "threshold_days": 547},
            "checklist": ["Delay in trial not attributable to the accused [to be verified from the order sheet]"]}}
        text = docx_text(legal_aid_docx.build_release_docx(alert))
        for needle in (legal_aid_docx.RELEASE_TITLE, "SC/2023/1", "1383 days", "[to be verified]", "not legal advice"):
            self.assertIn(needle, text)

    def test_custody_review_request_is_review_only_and_supports_hindi_and_telugu(self):
        alert = {"case_id": "SC/2023/1", "act": "BNS", "section": "303(2)", "custody_since": "2023-01-12",
                 "max_sentence_years": "7 years", "details": {"release_check": {
                     "custody_days": 1383, "threshold_days": 851, "basis": "one-third (first-time offender)"}}}
        english = docx_text(legal_aid_docx.build_superintendent_docx(alert))
        for needle in (legal_aid_docx.SUPERINTENDENT_TITLE, "BNS Section 303(2)", "12.01.2023",
                       "a maximum sentence of 7 years", "not a legal finding on eligibility", "[to be verified]"):
            self.assertIn(needle, english)
        self.assertNotIn("is entitled to release", english)

        hindi = docx_text(legal_aid_docx.build_superintendent_docx(alert, "hi"))
        self.assertIn("धारा 479(3)", hindi)
        self.assertIn("पात्रता का कानूनी निर्णय नहीं", hindi)
        self.assertIn("एक-तिहाई", hindi)

        telugu = docx_text(legal_aid_docx.build_superintendent_docx(alert, "te"))
        self.assertIn("479వ విభాగం (3)", telugu)
        self.assertIn("గరిష్ఠ శిక్షాకాలంలో మూడింట ఒక వంతు", telugu)
        self.assertIn("చట్టపరమైన అర్హతపై తుది నిర్ణయం కాదు", telugu)
        self.assertIn("న్యాయ సలహా కాదు", telugu)
        self.assertIn("జామీనుపై", telugu)
        self.assertIn("విచారణలో ఉన్న ఇతర వ్యాజ్యాలు", telugu)
        for hindi_or_english_loanword in ("సెక్షన్", "పెండింగ్", "బెయిల్", "సూపరింటెండెంట్"):
            self.assertNotIn(hindi_or_english_loanword, telugu)
        self.assertNotIn("Draft generated by Nyaya Mitra", telugu)

    def test_superintendent_letter_rejects_unsupported_language(self):
        with self.assertRaises(ValueError):
            legal_aid_docx.build_superintendent_docx({}, "kn")

    def test_superintendent_letter_keeps_missing_facts_as_placeholders(self):
        text = docx_text(legal_aid_docx.build_superintendent_docx({}))
        for placeholder in ("[to be verified]", "[Act and section to be verified]"):
            self.assertIn(placeholder, text)
        self.assertIn("not a legal finding on eligibility", text)

        telugu = docx_text(legal_aid_docx.build_superintendent_docx({}, "te"))
        self.assertIn("[ధృవీకరించాలి]", telugu)
        self.assertIn("[చట్టం మరియు విభాగం ధృవీకరించాలి]", telugu)
        self.assertNotIn("[to be verified]", telugu)


if __name__ == "__main__":
    unittest.main()
