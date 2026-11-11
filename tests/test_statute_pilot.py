"""Statute CSV validation and pilot metrics. Run: python -m unittest discover -s tests"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)

from nyayavedika import pilot_metrics, statute_import  # noqa: E402

TODAY = date(2026, 11, 5)


def _row(**k):
    base = {"act": "BNS", "section": "303(2)", "offence": "Theft", "max_sentence_years": "3", "life_or_death": "no",
            "bailable": "no", "compoundable": "yes", "verified_by": "A. Lawyer", "source": "indiacode.nic.in"}
    base.update(k)
    return base


class StatuteImportTests(unittest.TestCase):
    def test_valid_row_is_loaded_and_marked_verified(self):
        rows, problems = statute_import.parse_rows([_row()], TODAY)
        self.assertEqual(problems, [])
        self.assertEqual(rows[0]["max_sentence_years"], 3.0)
        self.assertIn("verified by A. Lawyer on 2026-11-05", rows[0]["note"])

    def test_row_without_verifier_is_marked_unverified(self):
        rows, _ = statute_import.parse_rows([_row(verified_by="")], TODAY)
        self.assertEqual(rows[0]["note"], "UNVERIFIED")

    def test_life_row_has_no_years(self):
        rows, problems = statute_import.parse_rows([_row(max_sentence_years="", life_or_death="yes")], TODAY)
        self.assertEqual(problems, [])
        self.assertIsNone(rows[0]["max_sentence_years"])
        self.assertTrue(rows[0]["life_or_death"])

    def test_bad_rows_are_reported_not_guessed(self):
        bad = [_row(max_sentence_years=""), _row(section="1", max_sentence_years="abc"),
               _row(section="2", life_or_death="yes", max_sentence_years="5"), _row(section="3", max_sentence_years="0"),
               _row(act=""), _row(section="4", bailable="maybe")]
        rows, problems = statute_import.parse_rows(bad, TODAY)
        self.assertEqual(rows, [])
        self.assertEqual(len(problems), 6)

    def test_duplicate_in_file_is_rejected(self):
        rows, problems = statute_import.parse_rows([_row(), _row()], TODAY)
        self.assertEqual(len(rows), 1)
        self.assertEqual(len(problems), 1)


class PilotMetricsTests(unittest.TestCase):
    ROWS = [
        {"manual_status": "eligible", "tool_status": "eligible", "lawyer_verdict": "eligible", "manual_minutes": "40", "tool_minutes": "10",
         "days_over_limit": "100", "application_filed": "yes", "outcome": "released"},
        {"manual_status": "not_eligible", "tool_status": "needs_review", "lawyer_verdict": "not_eligible", "manual_minutes": "30", "tool_minutes": "12",
         "days_over_limit": "20", "application_filed": "no", "outcome": "none"},
        {"manual_status": "eligible", "tool_status": "not_eligible", "lawyer_verdict": "eligible", "manual_minutes": "", "tool_minutes": "",
         "days_over_limit": "0", "application_filed": "no", "outcome": "none"},
        {"manual_status": "not_eligible", "tool_status": "not_eligible", "lawyer_verdict": "not_eligible", "manual_minutes": "20", "tool_minutes": "8",
         "days_over_limit": "", "application_filed": "yes", "outcome": "pending"},
    ]

    def test_metrics(self):
        m = pilot_metrics.summarise(self.ROWS)
        self.assertEqual(m["cases_screened"], 4)
        self.assertEqual(m["flagged_for_release"], 2)
        self.assertEqual(m["precision"], 0.5)      # 1 of 2 flagged confirmed
        self.assertEqual(m["recall"], 0.5)         # 1 of 2 qualifying flagged
        self.assertEqual(m["accuracy"], 0.5)       # 2 of 4 matched tool results agree with the lawyer
        self.assertEqual(m["manual_accuracy"], 1.0)  # 4 of 4 manual results agree with the lawyer
        self.assertEqual(m["accuracy_comparison_cases"], 4)
        self.assertEqual(m["median_manual_minutes"], 30.0)
        self.assertEqual(m["median_tool_minutes"], 10.0)
        self.assertEqual(m["median_minutes_saved"], 18.0)
        self.assertEqual(m["median_time_saved_pct"], 60)
        self.assertEqual(m["cases_with_timing"], 3)
        self.assertEqual((m["people_held_past_limit"], m["days_over_limit_total"]), (2, 120))
        self.assertEqual((m["applications_filed"], m["released"], m["pending"]), (2, 1, 1))

    def test_empty_log_does_not_crash_or_invent_numbers(self):
        m = pilot_metrics.summarise([])
        self.assertEqual(m["cases_screened"], 0)
        self.assertIsNone(m["precision"])
        self.assertIsNone(m["accuracy"])
        self.assertIsNone(m["manual_accuracy"])
        self.assertEqual(m["accuracy_comparison_cases"], 0)
        self.assertIsNone(m["median_tool_minutes"])
        self.assertIsNone(m["median_minutes_saved"])
        self.assertIn("n/a", pilot_metrics.to_markdown(m))


if __name__ == "__main__":
    unittest.main()
