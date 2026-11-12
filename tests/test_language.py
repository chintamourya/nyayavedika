import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _testenv  # noqa: E402,F401

import unittest

from nyayavedika import llm  # noqa: E402


class ScriptedTranslator:
    def __init__(self, translations=None, error=None):
        self.translations = translations or []
        self.error = error

    def structured(self, _model, _system, _messages, schema, **_kwargs):
        if self.error:
            raise self.error
        if schema is not llm.LanguageRewrite:
            raise AssertionError(f"Unexpected schema: {schema.__name__}")
        return {"translations": self.translations}


class LanguageOutputTests(unittest.TestCase):
    def tearDown(self):
        llm.set_backend(None)

    def test_selected_language_rewrites_mixed_texts_and_preserves_order(self):
        llm.set_backend(ScriptedTranslator([
            "मैं आवेदन कैसे करूँ? DLSA से संपर्क करें।",
        ]))

        result = llm.enforce_language(["How can I apply?"], "Hindi")

        self.assertEqual(result, ["मैं आवेदन कैसे करूँ? DLSA से संपर्क करें।"])

        llm.set_backend(ScriptedTranslator(["తెలుగులో సమాధానం ఇస్తాను।"]))
        self.assertEqual(llm.enforce_language(["I will answer in Telugu."], "Telugu"), ["తెలుగులో సమాధానం ఇస్తాను।"])

    def test_failed_or_incomplete_rewrite_keeps_original_text(self):
        original = ["English with తెలుగు."]
        llm.set_backend(ScriptedTranslator(error=RuntimeError("provider unavailable")))
        self.assertEqual(llm.enforce_language(original, "Hindi"), original)

        llm.set_backend(ScriptedTranslator(["English only"]))
        self.assertEqual(llm.enforce_language(original, "Hindi"), original)

    def test_rewrite_that_changes_citation_numbers_is_rejected(self):
        original = ["See Section 12 [1]."]
        llm.set_backend(ScriptedTranslator(["धारा 13 [2] देखें।"]))

        self.assertEqual(llm.enforce_language(original, "Hindi"), original)


if __name__ == "__main__":
    unittest.main()
