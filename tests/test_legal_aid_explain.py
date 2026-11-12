"""5-question guide: the rules decide, the legal-aid index supplies passages, one model call explains (template offline)."""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import legal_aid, llm  # noqa: E402

KB = {"engine": "keyword (local)", "secondary_only_note": None, "passages": [
    {"text": "Women are entitled to free legal services under Section 12(c).", "heading": "Who is eligible?",
     "source_url": "https://nalsa.gov.in/legal-aid/", "authority": "primary", "last_verified": "2026-10-01"}]}


def search(query, top_k):
    search.last = query
    return KB


class ExplainTests(unittest.TestCase):
    def setUp(self):
        self.elig = legal_aid.check_eligibility({"woman": True, "state": "Telangana"})

    def tearDown(self):
        llm.set_backend(None)

    def test_offline_template_keeps_the_rules_decision_and_cites(self):
        out = legal_aid.explain(self.elig, search=search)
        self.assertEqual(out["engine"], "template")
        self.assertIn("likely entitled", out["answer"])
        self.assertEqual(out["used"], [1])
        self.assertEqual(out["sources"][0]["source_url"], "https://nalsa.gov.in/legal-aid/")
        self.assertIn("woman", search.last.lower())  # the query is built from the grounds

    def test_model_explains_with_cited_passages_in_one_call(self):
        calls = []

        class Backend:
            def structured(self, model, system, messages, schema, **kw):
                calls.append(messages[-1]["content"])
                return {"answer": "As a woman you can get a free lawyer [1].", "next_steps": ["Visit the DLSA"], "used": [1, 2, 7]}

        llm.set_backend(Backend())
        out = legal_aid.explain(self.elig, "my husband took my house", "English", search=search)
        self.assertEqual((out["engine"], out["used"]), ("llm", [1, 2]))  # passage 7 does not exist: dropped
        self.assertEqual(len(calls), 1)
        self.assertIn("Section 12(c)", calls[0])
        self.assertIn("Free legal aid: who is eligible and how to get it", calls[0])
        self.assertTrue(any(source["heading"] == "Free legal aid: who is eligible and how to get it"
                            for source in out["sources"]))

    def test_selected_hindi_rewrites_the_explanation_and_next_steps(self):
        prompts = []

        class Backend:
            def structured(self, _model, system, messages, schema, **_kw):
                prompts.append(system)
                if schema is legal_aid.Explanation:
                    return {"answer": "You may get a free lawyer.", "next_steps": ["Visit the DLSA"], "used": [1]}
                if schema is llm.LanguageRewrite:
                    return {"translations": ["आपको निःशुल्क वकील मिल सकता है।", "डीएलएसए जाएँ।"]}
                raise AssertionError(f"Unexpected schema: {schema.__name__}")

        llm.set_backend(Backend())
        out = legal_aid.explain(self.elig, language="Hindi", search=search)

        self.assertIn("exclusively in the selected", prompts[0])
        self.assertIn("Hindi", prompts[0])
        self.assertEqual(out["answer"], "आपको निःशुल्क वकील मिल सकता है।")
        self.assertEqual(out["next_steps"], ["डीएलएसए जाएँ।"])

    def test_model_failure_falls_back_to_template(self):
        class Busy:
            def structured(self, *a, **kw):
                raise RuntimeError("Error code: 429")

        llm.set_backend(Busy())
        self.assertEqual(legal_aid.explain(self.elig, search=search)["engine"], "template")

    def test_question_uses_local_index_before_web(self):
        web_calls = []
        local = {"engine": "keyword (local)", "passages": [{
            "text": "Apply at the District Legal Services Authority.", "heading": "How to apply",
            "source_url": "https://nalsa.gov.in/legal-aid/", "authority": "primary", "last_verified": "2026-10-01"}]}
        out = legal_aid.answer_question("Where do I apply?", search=lambda *args: local,
                                       web_search=lambda *args, **kwargs: web_calls.append(args) or {})
        self.assertEqual(out["engine"], "rules")
        self.assertFalse(out["web_search_used"])
        self.assertFalse(web_calls)
        self.assertIn("District Legal Services Authority", out["answer"])
        self.assertEqual(out["sources"][0]["source_url"], "https://nalsa.gov.in/legal-aid/")

    def test_question_uses_official_web_when_local_index_has_no_match(self):
        web = {"answer": "Contact the relevant DLSA.", "results": [{
            "title": "NALSA", "url": "https://nalsa.gov.in/", "content": "Contact the DLSA."}]}
        out = legal_aid.answer_question("How can I contact the DLSA?",
                                       search=lambda *args: {"engine": "keyword (local)", "passages": []},
                                       web_search=lambda *args, **kwargs: web)
        self.assertTrue(out["web_search_used"])
        self.assertEqual(out["sources"][0]["authority"], "official web search")
        self.assertIn("Contact the relevant DLSA", out["answer"])

    def test_question_includes_uploaded_document_as_a_source(self):
        out = legal_aid.answer_question("What does this say?", document_text="[order.txt, page 1]\nThe hearing is on 12 June.",
                                       document_name="order.txt", search=lambda *args: {"passages": []},
                                       web_search=lambda *args, **kwargs: {})
        self.assertEqual(out["sources"][0]["heading"], "order.txt")
        self.assertIn("uploaded document", out["sources"][0]["authority"])
        self.assertIn("The hearing is on 12 June.", out["answer"])


if __name__ == "__main__":
    unittest.main()
