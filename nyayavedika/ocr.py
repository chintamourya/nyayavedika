"""Open-source OCR for scanned case files: native text first, Tesseract only where needed.

Adapted from backend-case-pdf-main/server/ocr_pipeline/casepdf_ocr_pipeline.py
(page_needs_ocr density heuristic, image_to_data word-confidence filter), re-implemented on
permissive libraries: pypdf (BSD-3) for native text, pypdfium2 (Apache-2.0/BSD-3) to rasterise,
pytesseract (Apache-2.0) + Tesseract (Apache-2.0) with Indic language packs.
"""
import io
import logging
import re
from typing import Dict, List

from . import config

logger = logging.getLogger(__name__)

MIN_ALNUM_CHARS_PER_PAGE = config.OCR_MIN_ALNUM_CHARS_PER_PAGE
MIN_CHARS_PER_PAGE_AREA = config.OCR_MIN_CHARS_PER_PAGE_AREA
MIN_WORD_CONFIDENCE = config.OCR_MIN_WORD_CONFIDENCE
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".webp")


def page_needs_ocr(native_text: str, page_width: float, page_height: float) -> bool:
    visible = re.sub(r"[^A-Za-z0-9ऀ-෿]", "", native_text)  # Latin + Indic scripts
    if len(visible) < MIN_ALNUM_CHARS_PER_PAGE:
        return True
    return len(visible) / max(page_width * page_height, 1.0) < MIN_CHARS_PER_PAGE_AREA


def capabilities() -> Dict:
    caps = {}
    for mod in ("pypdf", "pypdfium2", "pytesseract"):
        try:
            __import__(mod)
            caps[mod] = True
        except ImportError:
            caps[mod] = False
    if caps["pytesseract"]:
        try:
            import pytesseract
            caps["tesseract_version"] = str(pytesseract.get_tesseract_version())
        except Exception:
            caps["pytesseract"] = False
            caps["tesseract_version"] = "binary not found"
    return caps


def _ocr_image(img) -> Dict:
    import pytesseract
    data = pytesseract.image_to_data(img, lang=config.TESSERACT_LANG, output_type=pytesseract.Output.DICT)
    words, confs = [], []
    for i, raw in enumerate(data.get("text", [])):
        txt = (raw or "").strip()
        if not txt:
            continue
        try:
            conf = float(data["conf"][i])
        except (TypeError, ValueError):
            conf = -1.0
        if 0 <= conf < MIN_WORD_CONFIDENCE:
            continue
        if conf >= 0:
            confs.append(conf)
        # keep line breaks so paragraph splitting still works downstream
        if words and data["line_num"][i] != data["line_num"][i - 1]:
            words.append("\n")
        words.append(txt)
    text = " ".join(words).replace(" \n ", "\n")
    return {"text": text, "confidence": round(sum(confs) / len(confs), 1) if confs else None}


def extract(data: bytes, filename: str) -> List[Dict]:
    """Return per-page dicts: {page, text, source: native|ocr|text, confidence}."""
    name = filename.lower()
    if name.endswith(IMAGE_EXTS):
        from PIL import Image
        r = _ocr_image(Image.open(io.BytesIO(data)))
        return [{"page": 1, "text": r["text"], "source": "ocr", "confidence": r["confidence"]}]
    if name.endswith(".docx"):
        from docx import Document
        document = Document(io.BytesIO(data))
        parts = [paragraph.text for paragraph in document.paragraphs if paragraph.text.strip()]
        parts.extend(
            " | ".join(cell.text.strip() for cell in row.cells if cell.text.strip())
            for table in document.tables for row in table.rows
        )
        return [{"page": 1, "text": "\n".join(parts), "source": "text", "confidence": None}]
    if not name.endswith(".pdf"):
        return [{"page": 1, "text": data.decode("utf-8", errors="replace"), "source": "text", "confidence": None}]

    caps = capabilities()
    if not caps["pypdf"]:
        raise RuntimeError("PDF support needs pypdf installed")
    import pypdf
    try:
        reader = pypdf.PdfReader(io.BytesIO(data))
        pages = []
        pdfium_doc = None
        for i, page in enumerate(reader.pages):
            native = page.extract_text() or ""
            w, h = float(page.mediabox.width), float(page.mediabox.height)
            entry = {"page": i + 1, "text": native, "source": "native", "confidence": None}
            if page_needs_ocr(native, w, h):
                if caps["pypdfium2"] and caps["pytesseract"]:
                    import pypdfium2 as pdfium
                    pdfium_doc = pdfium_doc or pdfium.PdfDocument(data)
                    img = pdfium_doc[i].render(scale=config.OCR_DPI / 72).to_pil()
                    r = _ocr_image(img)
                    if len(re.sub(r"\W", "", r["text"])) > len(re.sub(r"\W", "", native)):
                        entry.update(text=r["text"], source="ocr", confidence=r["confidence"])
                else:
                    entry["source"] = "needs_ocr_unavailable"
            pages.append(entry)
    except pypdf.errors.PdfReadError as exc:
        raise ValueError(f"Invalid or unreadable PDF: {exc}") from exc
    return pages
