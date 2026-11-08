"""Offline tests - run with:  python -m unittest discover -s tests"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import unittest
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import documents, legal_aid, sample_data, scheduler, offline_summary, triage, vectorstore  # noqa: E402

TODAY = date(2026, 10, 26)


class TriageTests(unittest.TestCase):
    def test_undertrial_release_flag(self):
        case = {"case_id": "SC/2020/1", "case_type": "criminal_trial", "filing_date": "2020-01-01", "stage": "evidence",
                "accused_in_custody": True, "custody_since": "2021-01-01", "max_sentence_years": 7,
                "first_time_offender": False, "advocate_ids": []}
        r = triage.score_case(case, TODAY)
        self.assertIn("UNDERTRIAL_RELEASE_ELIGIBLE", r["flags"])
        self.assertIn("479", r["recommended_route"])
        self.assertEqual(r["band"], "Critical")

    def test_life_sentence_not_release_eligible(self):
        case = {"case_id": "x", "case_type": "criminal_trial", "accused_in_custody": True,
                "custody_since": "2010-01-01", "max_sentence_years": "life"}
        self.assertNotIn("UNDERTRIAL_RELEASE_ELIGIBLE", triage.score_case(case, TODAY)["flags"])

    def test_cheque_bounce_goes_to_adr(self):
        case = {"case_id": "CC/2022/1", "case_type": "cheque_bounce", "filing_date": "2022-05-01", "stage": "evidence"}
        self.assertIn("Lok Adalat", triage.score_case(case, TODAY)["recommended_route"])

    def test_scores_sorted_and_bounded(self):
        results = triage.triage_all(sample_data.generate(80, today=TODAY), TODAY)
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))
        self.assertTrue(all(0 <= s <= 100 for s in scores))

    def test_free_text_classification(self):
        out = triage.classify_free_text("My 67 year old father is in judicial custody since 2022 in a theft case")
        self.assertEqual(out["case_type"], "criminal_trial")
        self.assertTrue(out["accused_in_custody"])
        self.assertTrue(out["senior_citizen"])
        self.assertEqual(out["custody_since"], "2022-01-01")
        self.assertEqual(out["max_sentence_years"], 3)
        case = {"case_id": "NEW", "filing_date": "2026-10-26", **out}
        self.assertIn("UNDERTRIAL_RELEASE_ELIGIBLE", triage.score_case(case, TODAY)["flags"])


class SchedulerTests(unittest.TestCase):
    def setUp(self):
        self.results = triage.triage_all(sample_data.generate(120, today=TODAY), TODAY)
        self.plan = scheduler.build_cause_list(self.results, TODAY, days=5)

    def test_capacity_respected(self):
        for day in self.plan["calendar"]:
            for b in day["benches"]:
                self.assertLessEqual(b["expected_minutes"], 300)

    def test_no_advocate_double_booking(self):
        for day in self.plan["calendar"]:
            seen = {}
            for b in day["benches"]:
                for c in b["cases"]:
                    start, end = c["slot"].split("-")
                    for adv in c["advocates"]:
                        for ob, s, e in seen.get(adv, []):
                            if ob != b["bench_id"]:
                                self.assertFalse(start < e and s < end, f"{adv} double-booked on {day['date']}")
                        seen.setdefault(adv, []).append((b["bench_id"], start, end))

    def test_critical_cases_listed_first(self):
        m = self.plan["metrics"]
        self.assertEqual(m["critical_listed"], m["critical_total"])
        self.assertGreaterEqual(m["critical_listed"], m["baseline_fifo"]["critical_listed"])

    def test_skips_weekends(self):
        self.assertTrue(all(d.weekday() < 5 for d in scheduler.working_days(TODAY, 10)))


class SummarizerTests(unittest.TestCase):
    def test_sample_judgment(self):
        text = (ROOT / "data" / "sample_judgment.txt").read_text(encoding="utf-8")
        s = offline_summary.summarize(text)
        self.assertEqual(s["engine"], "heuristic")
        self.assertTrue(s["is_legal_document"])
        self.assertEqual(len(s["issues"]), 3)
        self.assertEqual(s["timeline"][0]["date"], "05.06.2016")
        self.assertEqual(s["case_details"]["case_number"], "CRIMINAL APPEAL No. 412 of 2021")
        self.assertIn("allowed", (s["outcome"] or "").lower())
        self.assertTrue(any("304" in x for x in s["statutes_cited"]))
        self.assertTrue(s["triage_signals"]["custody"])

    def test_empty_document_rejected(self):
        with self.assertRaises(ValueError):
            offline_summary.summarize("   ")


class DocumentTests(unittest.TestCase):
    def test_redaction(self):
        out = documents.redact_pii("Call 9876543210 or mail x.y@example.org, Aadhaar 1234 5678 9012, PAN ABCDE1234F")
        for token in ("[PHONE]", "[EMAIL]", "[AADHAAR]", "[PAN]"):
            self.assertIn(token, out)
        self.assertNotIn("9876543210", out)

    def test_chunking_keeps_pages(self):
        chunks, full = documents.paragraph_chunking(["a\n" * 120, "b\n" * 10], max_lines=50, overlap=5)
        self.assertEqual(chunks[-1]["page"], 2)
        self.assertIn("b", full)


class VectorstoreTests(unittest.TestCase):
    def test_upsert_chunks_passes_pinecone_arguments_by_keyword(self):
        from unittest.mock import Mock, patch

        index = Mock()
        chunks = [{"id": "doc-1", "text": "judgment text", "case_id": "case-1"}]
        with patch.object(vectorstore, "_get_index", return_value=index):
            count = vectorstore.upsert_chunks("casefiles", chunks)

        self.assertEqual(count, 1)
        index.upsert_records.assert_called_once_with(
            namespace="casefiles",
            records=[{"_id": "doc-1", "chunk_text": "judgment text", "case_id": "case-1"}],
        )

    def test_search_normalizes_id_score_and_metadata_shapes(self):
        from unittest.mock import Mock, patch

        index = Mock()
        index.search.return_value = {"result": {"hits": [
            {"id": "doc-1", "score": 0.91234,
             "fields": {"chunk_text": "petition filed", "page": 3, "doc_id": "doc-1"}},
            {"_id": "doc-2", "_score": 0.81234,
             "metadata": {"chunk_text": "reply received", "page": 4}},
            {"id": "broken", "fields": {"chunk_text": "missing score"}},
        ]}}
        with patch.object(vectorstore, "_get_index", return_value=index):
            results = vectorstore.search("advocate-documents", "filing date")

        self.assertEqual(results, [
            {"id": "doc-1", "score": 0.9123, "text": "petition filed", "page": 3, "doc_id": "doc-1"},
            {"id": "doc-2", "score": 0.8123, "text": "reply received", "page": 4},
        ])

    def test_search_uses_hit_attributes_when_to_dict_raises_key_error(self):
        from unittest.mock import Mock, patch

        class PineconeHit:
            id = "doc-attribute"
            score = 0.76543
            fields = {"chunk_text": "hearing was scheduled", "page": 7}

            def to_dict(self):
                raise KeyError("_id")

        index = Mock()
        index.search.return_value = {"result": {"hits": [PineconeHit()]}}
        with patch.object(vectorstore, "_get_index", return_value=index):
            results = vectorstore.search("advocate-documents", "hearing")

        self.assertEqual(results, [
            {"id": "doc-attribute", "score": 0.7654, "text": "hearing was scheduled", "page": 7},
        ])


class LegalAidTests(unittest.TestCase):
    def test_income_ground(self):
        r = legal_aid.check_eligibility({"annual_income": 120000})
        self.assertTrue(r["eligible"])
        self.assertEqual(r["grounds"][0]["clause"], "12(h)")

    def test_not_eligible(self):
        self.assertFalse(legal_aid.check_eligibility({"annual_income": 5000000})["eligible"])

    def test_template_application(self):
        applicant = {"in_custody": True}
        elig = legal_aid.check_eligibility(applicant)
        d = legal_aid.draft_application(applicant, elig, "Arrested in a theft case, cannot afford a lawyer")
        self.assertEqual(d["engine"], "template")
        self.assertIn("12(g)", d["application"])


if __name__ == "__main__":
    unittest.main()
