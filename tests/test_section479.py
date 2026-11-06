"""Sec. 479 BNSS rule engine against the hand-derived gold set. Run: python -m unittest discover -s tests"""
import json
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import unittest
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import triage  # noqa: E402

TODAY = date(2026, 11, 5)
GOLD = json.loads((ROOT / "tests" / "gold_479.json").read_text())["cases"]


def _case(g):
    case = {"accused_in_custody": g.get("in_custody", True), "max_sentence_years": g["max"], "first_time_offender": g["fto"]}
    if g["days"] is not None:
        case["custody_since"] = (TODAY - timedelta(days=g["days"])).isoformat()
    for k in ("section", "other_pending_cases", "life_or_death"):
        if k in g:
            case[k] = g[k]
    return case


class Section479GoldTests(unittest.TestCase):
    def test_gold_cases(self):
        wrong = []
        for g in GOLD:
            res = triage.undertrial_release_check(_case(g), TODAY)
            got = res["status"] if res else None
            if got != g["expect"]:
                wrong.append(f"{g['id']}: expected {g['expect']}, got {got}")
        self.assertEqual(wrong, [], "\n".join(wrong))

    def test_status_never_hides_a_crossed_threshold(self):
        """`eligible` stays the plain arithmetic, so older callers still see every case past the limit."""
        for g in GOLD:
            res = triage.undertrial_release_check(_case(g), TODAY)
            if res and res["status"] in ("eligible", "likely_eligible", "needs_review"):
                self.assertTrue(res["eligible"], g["id"])

    def test_needs_review_case_still_scores_critical_and_asks_for_review(self):
        case = {"case_id": "x", "case_type": "criminal_trial", "accused_in_custody": True, "first_time_offender": False,
                "custody_since": "2021-01-01", "max_sentence_years": 7, "section": "379, 420", "stage": "evidence"}
        r = triage.score_case(case, TODAY)
        self.assertIn("UNDERTRIAL_RELEASE_ELIGIBLE", r["flags"])
        self.assertTrue(r["needs_review"])
        self.assertEqual(r["band"], "Critical")


if __name__ == "__main__":
    unittest.main()
