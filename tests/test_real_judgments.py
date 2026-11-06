"""Real-world orders the synthetic samples do not cover: a High Court detention writ that is allowed.

An allowed / dismissed order is a decided matter: it must not enter the hearing queue, must not be
scored as an accused in custody, and a petitioner who is the detenu's wife is not a vulnerable party.
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika import extraction  # noqa: E402

COVER = ("IN THE HIGH COURT OF ANDHRA PRADESH AT AMARAVATI\nWRIT PETITION No.2163 OF 2024\n"
         "G.Shobha, W/o. A.Sasi Kumar ...Petitioner AND The State of Andhra Pradesh ...Respondents\n"
         "Cases referred: 1. AIR 1964 SC 334\nThis Court made the following:")
BODY = ("The writ petition challenges the order of detention passed under the Andhra Pradesh Prevention of "
        "Boot-Leggers, Dacoits, Drug Offenders, Gundas Act, 1986. The detenu was in judicial custody. "
        "The wife of the detenu has filed the present writ petition. The detention order is set aside. "
        "The writ petition is allowed and the detenu shall be set at liberty, if he is not required in any other case.")


def pages():
    return [{"page": 1, "text": COVER}, {"page": 2, "text": BODY}]


class DetentionWritTests(unittest.TestCase):
    def test_cover_page_is_an_order(self):
        self.assertEqual(extraction.classify_doc_type(COVER), "order")

    def test_detention_writ_is_habeas_corpus(self):
        draft = extraction.rules_draft(pages(), "order")
        self.assertEqual(draft.case_type.value, "habeas_corpus")

    def test_allowed_writ_is_disposed_and_not_in_custody(self):
        draft = extraction.rules_draft(pages(), "order")
        self.assertEqual(draft.status.value, "disposed")
        self.assertIs(draft.accused_in_custody.value, False)

    def test_petitioner_wife_is_not_a_vulnerable_party(self):
        self.assertIsNone(extraction.rules_draft(pages(), "order").woman_or_child.value)

    def test_disposed_case_needs_no_review(self):
        self.assertEqual(extraction.required_fields({"status": "disposed", "case_type": "habeas_corpus"}), ["case_type"])

    def test_pending_petition_is_unchanged(self):
        pend = [{"page": 1, "text": "PETITION under Section 438 BNSS. Application for anticipatory bail. The accused is "
                                    "in judicial custody since 02.01.2026."}]
        draft = extraction.rules_draft(pend, "petition")
        self.assertIsNone(draft.status.value)


if __name__ == "__main__":
    unittest.main()
