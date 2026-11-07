import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _testenv  # noqa: E402,F401

import tempfile
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import advocate, config, db, storage  # noqa: E402


PAGES = [
    {"page": 1, "text": "The petitioner filed this petition on 1 January 2024. The court issued notice.",
     "source": "native", "confidence": None},
    {"page": 2, "text": "The respondent filed a reply on 15 January 2024. The matter was listed.",
     "source": "ocr", "confidence": 95.0},
]


class AdvocateWorkspaceTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.old = config.DATABASE_URL, config.STORAGE_DIR
        config.DATABASE_URL = f"sqlite:///{self.tmp}/advocate.db"
        config.STORAGE_DIR = f"{self.tmp}/storage"
        db.reset_engine_for_tests(config.DATABASE_URL)
        self.workspace = advocate.create_workspace()["workspace_token"]
        self.other_workspace = advocate.create_workspace()["workspace_token"]

    def tearDown(self):
        db.reset_engine_for_tests(self.old[0])
        config.DATABASE_URL, config.STORAGE_DIR = self.old

    def upload(self):
        data = b"%PDF-1.4 test document"
        with mock.patch.object(advocate.intake, "pdf_page_count", return_value=len(PAGES)), \
                mock.patch.object(advocate.ocr, "extract", return_value=PAGES) as extract:
            result = advocate.upload_document(self.workspace, "petition.pdf", data)
        return result, extract

    def test_workspace_capability_is_required_to_read_an_uploaded_document(self):
        result, _ = self.upload()
        self.assertTrue(db.is_advocate_document(result["doc_id"]))
        self.assertEqual(len(storage.get_pages(result["doc_id"])), 2)
        with mock.patch.object(advocate.llm, "available", return_value=True), \
                mock.patch.object(advocate.summarise, "call") as generate:
            with self.assertRaises(advocate.AdvocateError) as error:
                advocate.generate_insight(self.other_workspace, result["doc_id"], "issues")
        self.assertEqual(error.exception.status, 404)
        generate.assert_not_called()

    def test_only_selected_insight_is_generated_and_extracted_pages_are_reused(self):
        result, extract = self.upload()
        report = advocate.InsightReport(sections=[advocate.InsightSection(
            title="Issues",
            points=[
                advocate.InsightPoint(text="The petition was filed on 1 January 2024.",
                                      page_refs=[1], evidence="filed this petition on 1 January 2024"),
                advocate.InsightPoint(text="The court decided the matter.",
                                      page_refs=[2], evidence="the court decided the matter"),
            ],
        )])
        with mock.patch.object(advocate.llm, "available", return_value=True), \
                mock.patch.object(advocate.summarise, "call", return_value=report) as generate:
            out = advocate.generate_insight(self.workspace, result["doc_id"], "issues")
        self.assertEqual(generate.call_count, 1)
        self.assertIn("Selected insight kind: issues", generate.call_args.args[1])
        self.assertEqual(out["grounded_points"], 1)
        self.assertEqual(out["sections"][0]["points"][0]["page_refs"], [1])
        self.assertEqual(extract.call_count, 1)
        self.assertEqual(out["ocr_pages"], 1)

    def test_bad_workspace_and_unavailable_model_fail_explicitly(self):
        with self.assertRaises(advocate.AdvocateError) as bad_workspace:
            advocate.upload_document("invalid", "petition.pdf", b"%PDF-")
        self.assertEqual(bad_workspace.exception.status, 403)
        result, _ = self.upload()
        with mock.patch.object(advocate.llm, "available", return_value=False):
            with self.assertRaises(advocate.AdvocateError) as unavailable:
                advocate.generate_insight(self.workspace, result["doc_id"], "facts")
        self.assertEqual(unavailable.exception.status, 503)

    def test_azure_connection_failure_has_actionable_message(self):
        result, _ = self.upload()

        class APIConnectionError(Exception):
            pass

        with mock.patch.object(advocate.llm, "available", return_value=True), \
                mock.patch.object(advocate.summarise, "call", side_effect=APIConnectionError()):
            with self.assertRaises(advocate.AdvocateError) as failure:
                advocate.generate_insight(self.workspace, result["doc_id"], "facts")

        self.assertEqual(failure.exception.status, 502)
        self.assertIn("outbound network, proxy", str(failure.exception))

    def test_upload_rejects_non_pdf_and_too_many_pages(self):
        with self.assertRaises(advocate.AdvocateError) as not_pdf:
            advocate.upload_document(self.workspace, "petition.txt", b"not a PDF")
        self.assertEqual(not_pdf.exception.status, 400)
        with mock.patch.object(advocate.intake, "pdf_page_count", return_value=MAX_PAGES + 1):
            with self.assertRaises(advocate.AdvocateError) as too_many:
                advocate.upload_document(self.workspace, "petition.pdf", b"%PDF-1.4 test")
        self.assertEqual(too_many.exception.status, 413)


MAX_PAGES = advocate.MAX_DOCUMENT_PAGES


if __name__ == "__main__":
    unittest.main()
