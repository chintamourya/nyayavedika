"""Role-token configuration checks. Run: python -m unittest discover -s tests"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika import auth, config  # noqa: E402


class TokenProblemTests(unittest.TestCase):
    def setUp(self):
        self._saved = (config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN)

    def tearDown(self):
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN = self._saved

    def _set(self, staff, lawyer, citizen):
        config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN = staff, lawyer, citizen

    def test_good_tokens_have_no_problems(self):
        self._set("s" * 20, "l" * 20, "c" * 20)
        self.assertEqual(auth.token_problems(), [])

    def test_shared_token_is_reported(self):
        self._set("same-long-token-123", "same-long-token-123", "c" * 20)
        problems = " ".join(auth.token_problems())
        self.assertIn("LAWYER", problems)
        self.assertIn("STAFF", problems)
        self.assertIn("local demos", problems)

    def test_short_or_placeholder_token_is_reported(self):
        self._set("abc", "l" * 20, "change-me-citizen-token")
        problems = " ".join(auth.token_problems())
        self.assertIn("STAFF", problems)
        self.assertIn("CITIZEN", problems)

    def test_empty_token_never_authenticates(self):
        self._set("", "", "")
        with self.assertRaises(auth.AuthError):
            auth.resolve("Bearer ")


if __name__ == "__main__":
    unittest.main()
