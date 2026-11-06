"""Document helpers: chunking, legal-document detection, PII redaction, file ids.

Adapted from backend-casechat-insights-multidoc-yasaswi-casechat-backend/source/readPDFv2.py
(paragraph_chunking, is_legal_document, generate_file_id). Text extraction / OCR lives in ocr.py.
This module has no third-party dependencies.
"""
import hashlib
import re
import uuid
from typing import Dict, List, Tuple

from . import config


def generate_file_id(input_bytes: bytes) -> str:
    """Deterministic id from file content, so re-uploads hit the same record."""
    if not input_bytes:
        raise ValueError("Cannot generate file ID from empty bytes")
    return str(uuid.UUID(hashlib.md5(input_bytes).hexdigest()))


def paragraph_chunking(pages: List[str], max_lines: int = config.CHUNK_MAX_LINES, overlap: int = config.CHUNK_OVERLAP_LINES) -> Tuple[List[Dict], str]:
    """Split pages into overlapping line windows, keeping page numbers for citations."""
    chunks, full_context = [], ""
    for p, text in enumerate(pages):
        full_context += text + "\n"
        lines = text.split("\n")
        i = 0
        while i < len(lines):
            end = min(i + max_lines, len(lines))
            chunk_text = "\n".join(lines[i:end]).strip()
            if chunk_text:
                chunks.append({"id": len(chunks) + 1, "page": p + 1, "text": chunk_text})
            if end == len(lines):
                break
            i += max_lines - overlap
    return chunks, full_context


def split_paragraphs(text: str) -> List[str]:
    """Split judgment text into numbered or blank-line separated paragraphs."""
    parts = re.split(r"\n\s*\n|\n(?=\s*\d{1,3}\.\s)", text)
    return [re.sub(r"\s+", " ", p).strip() for p in parts if p and p.strip()]


def is_legal_document(text: str) -> bool:
    """Heuristic: at least 3 of 5 legal indicators present."""
    case_number_pattern = r'\b(?:Case No|Appeal No|Writ Petition No|W\.P\.|Suit No|Criminal Case No|Crl\.A\.|O\.S\.)\.?\s*(?:\(\w+\)\s*)?(?:No\.?\s*)?\d+\s*(?:/|of)\s*\d+'
    party_names_pattern = r'\b[A-Z][\w.]*(?:\s+[A-Z][\w.]*)*\s+(?:vs?\.?|versus)\s+[A-Z][\w.]*'
    court_name_pattern = r'\b(Supreme Court|High Court|District Court|Sessions? Court|Family Court|Tribunal|Magistrate)\b'
    legal_keywords = ["Petitioner", "Respondent", "Appellant", "Judgment", "Order", "Accused", "Disposed"]
    legal_citation_pattern = r'\b(?:AIR|SCC|CriLJ|INSC)\b'
    score = sum([
        bool(re.search(case_number_pattern, text, re.I)),
        bool(re.search(party_names_pattern, text)),
        bool(re.search(court_name_pattern, text, re.I)),
        any(word.lower() in text.lower() for word in legal_keywords),
        bool(re.search(legal_citation_pattern, text)),
    ])
    return score >= 3


_PII_PATTERNS = [
    (re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]+"), "[EMAIL]"),
    (re.compile(r"\b\d{4}\s?\d{4}\s?\d{4}\b"), "[AADHAAR]"),
    (re.compile(r"\b[A-Z]{5}\d{4}[A-Z]\b"), "[PAN]"),
    (re.compile(r"(?<!\d)(?:\+91[\s-]?)?[6-9]\d{9}(?!\d)"), "[PHONE]"),
    (re.compile(r"\b(?:\d[ -]?){13,16}\b"), "[CARD]"),
]


def redact_pii(text: str) -> str:
    """Mask direct identifiers before text is sent to an external model or stored."""
    for pattern, token in _PII_PATTERNS:
        text = pattern.sub(token, text)
    return text
