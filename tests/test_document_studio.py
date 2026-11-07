import os
import sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import _testenv  # noqa: E402,F401

import base64
import io
import unittest
from unittest import mock

from nyayavedika import document_studio  # noqa: E402

try:
    from pypdf import PdfReader, PdfWriter
    HAS_PDF = True
except ImportError:
    HAS_PDF = False


def make_pdf(label, count=2):
    from reportlab.pdfgen import canvas
    out = io.BytesIO()
    pdf = canvas.Canvas(out, pagesize=(612, 792))
    for page in range(1, count + 1):
        pdf.drawString(60, 700, f"{label} page {page}")
        pdf.showPage()
    pdf.save()
    return out.getvalue()


def encoded(filename="case.pdf", data=None):
    return {"filename": filename, "content_base64": base64.b64encode(data or make_pdf("case")).decode("ascii")}


@unittest.skipUnless(HAS_PDF, "pypdf is not installed")
class DocumentStudioTests(unittest.TestCase):
    def pages(self, result, index=0):
        item = result["files"][index]
        data = base64.b64decode(item["content_base64"])
        return PdfReader(io.BytesIO(data))

    def test_preview_reports_page_count_and_page_numbers(self):
        result = document_studio.process("inspect", [encoded(data=make_pdf("preview", 3))])
        self.assertEqual(result["page_count"], 3)
        self.assertEqual(result["pages"], [1, 2, 3])

    def test_merge_and_split_preserve_page_content(self):
        merged = document_studio.process("merge", [
            encoded("first.pdf", make_pdf("first", 2)), encoded("second.pdf", make_pdf("second", 1)),
        ])
        reader = self.pages(merged)
        self.assertEqual(len(reader.pages), 3)
        self.assertIn("first page 1", reader.pages[0].extract_text())
        self.assertIn("second page 1", reader.pages[2].extract_text())
        split = document_studio.process("split", [encoded(data=make_pdf("volume", 3))],
                                        {"ranges": "1-2;3"})
        self.assertEqual([len(self.pages(split, i).pages) for i in range(2)], [2, 1])

    def test_reorder_rotate_and_remove_pages(self):
        file = encoded(data=make_pdf("sequence", 3))
        reordered = document_studio.process("reorder", [file], {"page_order": [3, 1, 2]})
        self.assertIn("page 3", self.pages(reordered).pages[0].extract_text())
        rotated = document_studio.process("rotate", [file], {"pages": [2], "degrees": 90})
        self.assertEqual(int(self.pages(rotated).pages[1].get("/Rotate", 0)), 90)
        removed = document_studio.process("remove", [file], {"pages": [2]})
        self.assertEqual(len(self.pages(removed).pages), 2)

    def test_bookmarks_clickable_index_page_numbers_and_ocr(self):
        file = encoded(data=make_pdf("brief", 2))
        bookmarked = document_studio.process("bookmarks", [file], {"items": "1 Cover\n2 Evidence"})
        self.assertEqual(len(self.pages(bookmarked).outline), 2)
        indexed = document_studio.process("index", [file], {"items": "2: Evidence"})
        index_reader = self.pages(indexed)
        self.assertEqual(len(index_reader.pages), 3)
        annots = index_reader.pages[0].get("/Annots")
        self.assertTrue(annots)
        destination = annots[0].get_object()["/Dest"]
        self.assertEqual(destination[0], index_reader.pages[2].indirect_reference)
        numbered = document_studio.process("page_numbers", [file], {"start_number": 4})
        self.assertIn("4", self.pages(numbered).pages[0].extract_text())
        with mock.patch.object(document_studio.ocr, "extract", return_value=[
            {"page": 1, "text": "Recognized legal text.", "source": "ocr", "confidence": 90.0},
        ]):
            ocr_result = document_studio.process("ocr", [file])
        text = base64.b64decode(ocr_result["download"]["content_base64"]).decode("utf-8")
        self.assertIn("Recognized legal text.", text)
        self.assertEqual(ocr_result["recognized_pages"], 1)

    def test_invalid_page_ranges_and_uploads_are_rejected(self):
        file = encoded(data=make_pdf("case", 2))
        with self.assertRaises(document_studio.StudioError):
            document_studio.process("reorder", [file], {"page_order": [1, 1]})
        with self.assertRaises(document_studio.StudioError):
            document_studio.process("remove", [file], {"pages": [1, 2]})
        with self.assertRaises(document_studio.StudioError):
            document_studio.process("merge", [file])
        with self.assertRaises(document_studio.StudioError):
            document_studio.process("index", [file], {"items": "99: Missing page"})


if __name__ == "__main__":
    unittest.main()
