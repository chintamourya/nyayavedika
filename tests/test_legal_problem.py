import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _testenv  # noqa: E402,F401

import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import legal_problem  # noqa: E402


UNDERSTANDING = {
    "category": "Property and land disputes",
    "facts": ["A neighbour blocked access to a shared path."],
    "parties": ["The resident", "The neighbour"],
    "dates": [],
    "jurisdiction": "Warangal, Telangana",
    "missing_info": [],
    "legal_question": "What official process may address a blocked access path?",
}
FORMULATIONS = {
    "first": "India Code Telangana property easement access path law",
    "second": "Telangana government authority procedure resolve blocked shared pathway",
}
ANSWER = {
    "understanding": "You describe a blocked shared path.",
    "laws_and_provisions": [{
        "text": "The cited source describes the applicable legal provision in Section 12.",
        "source_ids": [1],
        "basis": "source",
    }],
    "rights_and_protections": [],
    "possible_remedies": [],
    "authorities": [],
    "free_legal_aid": [],
    "next_steps": [],
    "limitations": [],
    "conflicts": [],
}


class LegalProblemResearchTests(unittest.TestCase):
    def test_extracts_then_searches_twice_and_returns_only_official_deduplicated_sources(self):
        structured_calls = []
        search_calls = []

        def structured(system, prompt, schema, **kwargs):
            structured_calls.append(schema.__name__)
            if schema is legal_problem.ProblemUnderstanding:
                payload = UNDERSTANDING
            elif schema is legal_problem.SearchFormulations:
                payload = FORMULATIONS
            elif schema is legal_problem.ResearchAnswer:
                payload = ANSWER
            else:
                self.fail(f"Unexpected schema: {schema.__name__}")
            return schema.model_validate(payload)

        def search(query, **kwargs):
            search_calls.append((query, kwargs))
            if len(search_calls) == 1:
                return {"results": [
                    {"title": "Official law", "url": "https://indiacode.nic.in/handle/123?tracking=1",
                     "content": "The official law includes Section 12.", "score": 0.9},
                    {"title": "Unofficial blog", "url": "https://example.com/law",
                     "content": "Section 12", "score": 1.0},
                    {"title": "Insecure result", "url": "http://example.gov.in/law",
                     "content": "Section 12", "score": 1.0},
                    {"title": "Irrelevant result", "url": "https://other.gov.in/",
                     "content": "Unrelated content", "score": 0.01},
                    {"title": "Non-standard port", "url": "https://other.gov.in:8443/",
                     "content": "Section 12", "score": 1.0},
                ]}
            return {"results": [
                {"title": "Duplicate official law", "url": "https://indiacode.nic.in/handle/123#part",
                 "content": "The official law includes Section 12 and a second passage.", "score": 0.95},
                {"title": "High Court", "url": "https://example.highcourt.gov.in/order",
                 "content": "A court order addresses property access.", "score": 0.8},
            ]}

        with mock.patch.object(legal_problem.llm, "available", return_value=True), \
                mock.patch.object(legal_problem.llm, "structured", side_effect=structured):
            out = legal_problem.research("A neighbour blocked our shared path.", "English", search_fn=search)

        self.assertEqual(structured_calls, ["ProblemUnderstanding", "SearchFormulations", "ResearchAnswer"])
        self.assertEqual(len(search_calls), 2)
        self.assertNotEqual(search_calls[0][0], search_calls[1][0])
        self.assertTrue(all(call[1]["trusted_only"] for call in search_calls))
        self.assertEqual(len(out["sources"]), 2)
        self.assertEqual(out["sources"][0]["url"], "https://indiacode.nic.in/handle/123")
        self.assertEqual(out["sources"][0]["query_ids"], [1, 2])
        self.assertEqual(out["answer"]["laws_and_provisions"][0]["source_ids"], [1])
        self.assertIn("retrieved_on", out)

    def test_requests_jurisdiction_before_formulating_or_searching(self):
        calls = []

        def structured(_system, _prompt, schema, **_kwargs):
            calls.append(schema.__name__)
            return schema.model_validate({
                **UNDERSTANDING,
                "jurisdiction": "",
                "missing_info": [],
            })

        search = mock.Mock()
        with mock.patch.object(legal_problem.llm, "available", return_value=True), \
                mock.patch.object(legal_problem.llm, "structured", side_effect=structured):
            out = legal_problem.research("My employer has withheld wages.", search_fn=search)

        self.assertTrue(out["needs_clarification"])
        self.assertTrue(any(term in item.lower() for item in out["understanding"]["missing_info"]
                            for term in ("jurisdiction", "state", "district", "city")))
        self.assertEqual(calls, ["ProblemUnderstanding"])
        search.assert_not_called()

    def test_no_reliable_results_never_generates_an_answer(self):
        schemas = []

        def structured(_system, _prompt, schema, **_kwargs):
            schemas.append(schema.__name__)
            payload = UNDERSTANDING if schema is legal_problem.ProblemUnderstanding else FORMULATIONS
            return schema.model_validate(payload)

        with mock.patch.object(legal_problem.llm, "available", return_value=True), \
                mock.patch.object(legal_problem.llm, "structured", side_effect=structured):
            out = legal_problem.research("My employer withheld wages.", jurisdiction="Telangana",
                                         search_fn=lambda *_a, **_k: {"results": []})

        self.assertTrue(out["no_reliable_sources"])
        self.assertEqual(schemas, ["ProblemUnderstanding", "SearchFormulations"])
        self.assertNotIn("answer", out)

    def test_invalid_queries_and_unavailable_providers_are_explicit(self):
        with mock.patch.object(legal_problem.llm, "available", return_value=False):
            with self.assertRaises(legal_problem.ResearchUnavailable):
                legal_problem.research("My wages were withheld.")

        with mock.patch.object(legal_problem.llm, "available", return_value=True), \
                mock.patch.object(legal_problem.llm, "structured", side_effect=[
                    legal_problem.ProblemUnderstanding.model_validate(UNDERSTANDING),
                    legal_problem.SearchFormulations(first="same query text", second="same query text"),
                ]):
            with self.assertRaises(legal_problem.InvalidResearchOutput):
                legal_problem.research("My wages were withheld.", jurisdiction="Telangana",
                                       search_fn=mock.Mock())

    def test_unlinked_or_unsupported_claims_are_removed(self):
        answer = legal_problem.ResearchAnswer.model_validate({
            **ANSWER,
            "laws_and_provisions": [
                {"text": "Section 479 provides a remedy.", "source_ids": [1], "basis": "source"},
                {"text": "A remedy is available at https://invented.example/", "source_ids": [1], "basis": "source"},
                {"text": "Uncited claim.", "source_ids": [], "basis": "source"},
            ],
        })
        sources = [{
            "id": 1, "excerpt": "This source discusses general process but no statute.",
            "url": "https://example.gov.in/",
        }]
        payload = legal_problem._answer_payload(answer, sources)
        self.assertEqual(payload["laws_and_provisions"], [])

    def test_bad_input_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "Describe your legal problem"):
            legal_problem.research("")
        with self.assertRaisesRegex(ValueError, "too long"):
            legal_problem.research("x" * (legal_problem.MAX_DESCRIPTION_CHARS + 1))


if __name__ == "__main__":
    unittest.main()
