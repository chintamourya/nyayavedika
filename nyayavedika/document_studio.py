"""In-memory PDF preparation operations for the Advocate Document Studio."""
import base64
import io
import re
from pathlib import Path
from typing import Dict, List, Tuple

from . import config, intake, ocr

MAX_FILES = 3
MAX_TOTAL_BYTES = config.MAX_UPLOAD_BYTES * MAX_FILES
MAX_TOTAL_PAGES = min(config.DEMO_MAX_PAGES, 50) * MAX_FILES
MIME_PDF = "application/pdf"


class StudioError(RuntimeError):
    def __init__(self, status: int, message: str):
        super().__init__(message)
        self.status = status


def _decode_files(files: List[Dict]) -> List[Tuple[str, bytes]]:
    if not isinstance(files, list) or not files or len(files) > MAX_FILES:
        raise StudioError(400, f"Choose between 1 and {MAX_FILES} PDF files.")
    decoded, total_bytes, total_pages = [], 0, 0
    for item in files:
        filename = Path(str(item.get("filename") or "document.pdf").replace("\\", "/")).name or "document.pdf"
        if Path(filename).suffix.lower() != ".pdf":
            raise StudioError(400, f"{filename}: only PDF files are supported.")
        encoded = item.get("content_base64")
        try:
            data = base64.b64decode(encoded, validate=True) if isinstance(encoded, str) else b""
        except (ValueError, base64.binascii.Error):
            raise StudioError(400, f"{filename}: file data is not valid base64.")
        if not data or b"%PDF-" not in data[:1024]:
            raise StudioError(400, f"{filename}: the file is empty or is not a valid PDF.")
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise StudioError(413, f"{filename}: file exceeds the {config.DEMO_MAX_FILE_MB} MB limit.")
        pages = intake.pdf_page_count(data)
        if pages is None:
            raise StudioError(400, f"{filename}: PDF is damaged or password-protected.")
        if pages > min(config.DEMO_MAX_PAGES, 50):
            raise StudioError(413, f"{filename}: PDF exceeds the 50-page-per-file limit.")
        total_bytes += len(data)
        total_pages += pages
        decoded.append((filename, data))
    if total_bytes > MAX_TOTAL_BYTES or total_pages > MAX_TOTAL_PAGES:
        raise StudioError(413, "The combined PDF upload exceeds the Document Studio processing limit.")
    return decoded


def _read(data: bytes):
    try:
        from pypdf import PdfReader
    except ImportError:
        raise StudioError(503, "PDF processing needs pypdf installed.")
    try:
        reader = PdfReader(io.BytesIO(data), strict=False)
        if reader.is_encrypted:
            raise StudioError(400, "Password-protected PDFs are not supported.")
        if not len(reader.pages):
            raise StudioError(400, "The PDF has no pages.")
        return reader
    except StudioError:
        raise
    except Exception as exc:
        raise StudioError(400, f"The PDF could not be opened ({type(exc).__name__}).")


def _writer_bytes(writer) -> bytes:
    output = io.BytesIO()
    try:
        writer.write(output)
    except Exception as exc:
        raise StudioError(422, f"The processed PDF could not be written ({type(exc).__name__}).")
    data = output.getvalue()
    if len(data) > MAX_TOTAL_BYTES * 2:
        raise StudioError(413, "The processed PDF exceeds the download size limit.")
    return data


def _pdf_result(filename: str, data: bytes) -> Dict:
    return {
        "files": [{
            "filename": filename,
            "mime_type": MIME_PDF,
            "content_base64": base64.b64encode(data).decode("ascii"),
        }]
    }


def _pages_arg(options: Dict, key: str, page_count: int) -> List[int]:
    raw = options.get(key, [])
    if isinstance(raw, str):
        try:
            values = [int(value) for value in re.split(r"[\s,;]+", raw.strip()) if value]
        except ValueError:
            raise StudioError(400, f"Enter valid page numbers for {key.replace('_', ' ')}.")
    elif isinstance(raw, list):
        try:
            values = [int(value) for value in raw]
        except (TypeError, ValueError):
            raise StudioError(400, f"Enter valid page numbers for {key.replace('_', ' ')}.")
    else:
        raise StudioError(400, f"Enter valid page numbers for {key.replace('_', ' ')}.")
    if not values or len(set(values)) != len(values) or any(page < 1 or page > page_count for page in values):
        raise StudioError(400, f"{key.replace('_', ' ').capitalize()} must be unique pages from 1 to {page_count}.")
    return values


def _page_overlay(page, text: str):
    try:
        from reportlab.pdfgen import canvas
    except ImportError:
        raise StudioError(503, "Page numbering and document indexes need reportlab installed.")
    width, height = float(page.mediabox.width), float(page.mediabox.height)
    output = io.BytesIO()
    pdf = canvas.Canvas(output, pagesize=(width, height), pageCompression=1)
    pdf.setFont("Helvetica", 9)
    pdf.drawCentredString(width / 2, 18, text)
    pdf.save()
    overlay = _read(output.getvalue())
    page.merge_page(overlay.pages[0])


def _ascii_label(value: str) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip().encode("latin-1", "replace").decode("latin-1")


def _ranges(raw, page_count: int) -> List[List[int]]:
    if isinstance(raw, list):
        groups = raw
    elif isinstance(raw, str):
        groups = [part.strip() for part in raw.split(";") if part.strip()]
    else:
        groups = []
    if not groups:
        raise StudioError(400, "Enter volume ranges separated by semicolons, such as 1-3;4-6.")
    parsed, used = [], set()
    for group in groups:
        text = str(group).strip()
        match = re.fullmatch(r"(\d+)\s*(?:-\s*(\d+))?", text)
        if not match:
            raise StudioError(400, "Each split volume must be a page number or range, such as 1-3.")
        start, end = int(match.group(1)), int(match.group(2) or match.group(1))
        if start > end or start < 1 or end > page_count:
            raise StudioError(400, f"Split ranges must be within pages 1 to {page_count}.")
        pages = list(range(start, end + 1))
        if used.intersection(pages):
            raise StudioError(400, "Split volume ranges cannot overlap.")
        used.update(pages)
        parsed.append(pages)
    return parsed


def process(operation: str, files: List[Dict], options: Dict = None) -> Dict:
    options = options or {}
    decoded = _decode_files(files)
    if operation not in {"inspect", "merge", "split", "reorder", "rotate", "remove", "ocr", "bookmarks", "index", "page_numbers"}:
        raise StudioError(400, "Choose a supported Document Studio operation.")
    if operation == "inspect":
        if len(decoded) != 1:
            raise StudioError(400, "Choose one PDF to preview its pages.")
        filename, data = decoded[0]
        reader = _read(data)
        return {"filename": filename, "page_count": len(reader.pages),
                "pages": list(range(1, len(reader.pages) + 1))}
    if operation == "merge":
        if len(decoded) < 2:
            raise StudioError(400, "Choose at least two PDFs to merge.")
        from pypdf import PdfWriter
        writer = PdfWriter()
        for _filename, data in decoded:
            writer.append(_read(data), import_outline=False)
        return _pdf_result("merged_documents.pdf", _writer_bytes(writer))
    if len(decoded) != 1:
        raise StudioError(400, "This operation uses exactly one PDF.")

    filename, data = decoded[0]
    reader = _read(data)
    page_count = len(reader.pages)

    if operation == "ocr":
        try:
            pages = ocr.extract(data, filename)
        except Exception as exc:
            raise StudioError(503, f"OCR could not process this PDF ({type(exc).__name__}). Check the OCR engine and try again.")
        results = [{
            "page": int(page.get("page") or i + 1),
            "text": page.get("text") or "",
            "source": page.get("source") or "unknown",
            "confidence": page.get("confidence"),
        } for i, page in enumerate(pages)]
        text = "\n\n".join(f"[Page {page['page']} · {page['source']}]\n{page['text']}" for page in results)
        return {
            "ocr_pages": results,
            "extracted_pages": len(results),
            "recognized_pages": sum(bool(page["text"].strip()) for page in results),
            "download": {
                "filename": f"{Path(filename).stem}_ocr.txt",
                "mime_type": "text/plain;charset=utf-8",
                "content_base64": base64.b64encode(text.encode("utf-8")).decode("ascii"),
            },
        }

    from pypdf import PdfWriter
    writer = PdfWriter()

    if operation == "split":
        if options.get("split_mode") == "pages":
            groups = [[n] for n in range(1, page_count + 1)]
        else:
            groups = _ranges(options.get("ranges"), page_count)
        outputs = []
        stem = Path(filename).stem
        for index, group in enumerate(groups, start=1):
            part = PdfWriter()
            for page_no in group:
                part.add_page(reader.pages[page_no - 1])
            outputs.extend(_pdf_result(f"{stem}_part_{index:02d}.pdf", _writer_bytes(part))["files"])
        return {"files": outputs}

    if operation == "reorder":
        order = _pages_arg(options, "page_order", page_count)
        if len(order) != page_count or set(order) != set(range(1, page_count + 1)):
            raise StudioError(400, f"Reorder must list every page exactly once (1 to {page_count}).")
        for page_no in order:
            writer.add_page(reader.pages[page_no - 1])
    elif operation == "rotate":
        selected = _pages_arg(options, "pages", page_count)
        try:
            degrees = int(options.get("degrees", 90))
        except (TypeError, ValueError):
            raise StudioError(400, "Rotation must be 90, 180, or 270 degrees clockwise.")
        if degrees not in (90, 180, 270):
            raise StudioError(400, "Rotation must be 90, 180, or 270 degrees clockwise.")
        for index, page in enumerate(reader.pages, start=1):
            if index in selected:
                page.rotate(degrees)
            writer.add_page(page)
    elif operation == "remove":
        removed = set(_pages_arg(options, "pages", page_count))
        if len(removed) == page_count:
            raise StudioError(400, "At least one page must remain in the PDF.")
        for index, page in enumerate(reader.pages, start=1):
            if index not in removed:
                writer.add_page(page)
    elif operation == "bookmarks":
        items = options.get("items")
        if isinstance(items, str):
            items = [line.strip() for line in items.splitlines() if line.strip()]
        if not isinstance(items, list) or not items:
            raise StudioError(400, "Add at least one bookmark as a page number and title, for example '1 Cover'.")
        for page in reader.pages:
            writer.add_page(page)
        for item in items:
            match = re.fullmatch(r"\s*(\d+)\s*[:|\t ]\s*(.{1,120})\s*", str(item))
            if not match:
                raise StudioError(400, "Bookmarks must use 'page title' or 'page: title' on each line.")
            page_no, title = int(match.group(1)), _ascii_label(match.group(2))
            if not 1 <= page_no <= page_count:
                raise StudioError(400, f"Bookmark page must be from 1 to {page_count}.")
            writer.add_outline_item(title, page_no - 1)
    elif operation == "page_numbers":
        try:
            start = int(options.get("start_number", 1))
        except (TypeError, ValueError):
            raise StudioError(400, "The starting page number must be a positive integer.")
        if not 1 <= start <= 999999:
            raise StudioError(400, "The starting page number must be from 1 to 999999.")
        for index, page in enumerate(reader.pages, start=start):
            writer.add_page(page)
            _page_overlay(writer.pages[-1], str(index))
    elif operation == "index":
        items = options.get("items")
        if isinstance(items, str):
            items = [line.strip() for line in items.splitlines() if line.strip()]
        if not isinstance(items, list) or not items:
            raise StudioError(400, "Add index entries as 'page: title', one per line.")
        entries = []
        for item in items:
            match = re.fullmatch(r"\s*(\d+)\s*[:|\t ]\s*(.{1,160})\s*", str(item))
            if not match:
                raise StudioError(400, "Index entries must use 'page: title' on each line.")
            page_no, title = int(match.group(1)), _ascii_label(match.group(2))
            if not 1 <= page_no <= page_count:
                raise StudioError(400, f"Index page must be from 1 to {page_count}.")
            entries.append((page_no, title))
        try:
            from reportlab.pdfgen import canvas
        except ImportError:
            raise StudioError(503, "Document indexes need reportlab installed.")
        width, height = float(reader.pages[0].mediabox.width), float(reader.pages[0].mediabox.height)
        if len(entries) > 40:
            raise StudioError(400, "A clickable index can contain at most 40 entries.")
        index_pdf = io.BytesIO()
        pdf = canvas.Canvas(index_pdf, pagesize=(width, height), pageCompression=1)
        pdf.setTitle("Document Index")
        pdf.setFont("Helvetica-Bold", 16)
        pdf.drawString(48, height - 48, "Document Index")
        pdf.setFont("Helvetica", 10)
        link_rects = []
        y = height - 78
        for page_no, title in entries:
            line = f"{page_no}. {title}"[:140]
            pdf.drawString(48, y, line)
            link_rects.append((page_no, (44, y - 3, min(width - 40, 48 + len(line) * 6), y + 12)))
            y -= 18
        pdf.save()
        writer.append(_read(index_pdf.getvalue()), import_outline=False)
        for page in reader.pages:
            writer.add_page(page)
        from pypdf.generic import ArrayObject, DictionaryObject, FloatObject, NameObject, NumberObject
        for page_no, rect in link_rects:
            # In-document links must point at the page object itself (a bare page index is only valid for remote links).
            target = writer.pages[page_no].indirect_reference
            link = DictionaryObject({
                NameObject("/Type"): NameObject("/Annot"),
                NameObject("/Subtype"): NameObject("/Link"),
                NameObject("/Rect"): ArrayObject([FloatObject(v) for v in rect]),
                NameObject("/Border"): ArrayObject([NumberObject(0), NumberObject(0), NumberObject(0)]),
                NameObject("/Dest"): ArrayObject([target, NameObject("/Fit")]),
            })
            index_page = writer.pages[0]
            annots = index_page.get(NameObject("/Annots"))
            if annots is None:
                annots = ArrayObject()
                index_page[NameObject("/Annots")] = annots
            else:
                annots = annots.get_object()
            annots.append(writer._add_object(link))
    else:
        raise StudioError(400, "Choose a supported Document Studio operation.")

    stem = Path(filename).stem
    output_name = {
        "reorder": f"{stem}_reordered.pdf",
        "rotate": f"{stem}_rotated.pdf",
        "remove": f"{stem}_pages_removed.pdf",
        "bookmarks": f"{stem}_bookmarked.pdf",
        "index": f"{stem}_indexed.pdf",
        "page_numbers": f"{stem}_numbered.pdf",
    }[operation]
    return _pdf_result(output_name, _writer_bytes(writer))
