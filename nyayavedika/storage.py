"""Local file storage keyed by content (demo stand-in for object storage).

    storage/<key>              the uploaded bytes (intake uses the sha256 hex digest as key and doc_id)
    storage/<key>.pages.json   extracted pages, cached so later steps never re-run OCR

Agents and job rows carry only the key; text is loaded from here when a step needs it.
"""
import hashlib
import json
import re
from pathlib import Path
from typing import Dict, List, Optional

from . import config

ROOT = Path(__file__).resolve().parents[1]


def root() -> Path:
    path = Path(config.STORAGE_DIR)
    path = path if path.is_absolute() else ROOT / path
    path.mkdir(parents=True, exist_ok=True)
    return path


def sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _path(key: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9-]{8,80}", key or ""):  # hex digests / uuids only: no path traversal
        raise ValueError("bad storage key")
    return root() / key


def put(data: bytes, key: Optional[str] = None) -> str:
    """Store bytes (idempotent). Returns the key (sha256 unless one is given)."""
    key = key or sha256(data)
    path = _path(key)
    if not path.exists():
        path.write_bytes(data)
    return key


def get(key: str) -> bytes:
    path = _path(key)
    if not path.exists():
        raise FileNotFoundError(f"stored file {key[:12]}... not found")
    return path.read_bytes()


def delete(key: str) -> None:
    path = _path(key)
    path.unlink(missing_ok=True)
    path.with_name(f"{key}.pages.json").unlink(missing_ok=True)


def uri(key: str) -> str:
    return f"{config.STORAGE_DIR}/{key}"


def put_pages(key: str, pages: List[Dict]) -> None:
    _path(key).with_name(f"{key}.pages.json").write_text(json.dumps(pages, ensure_ascii=False), encoding="utf-8")


def get_pages(key: str) -> Optional[List[Dict]]:
    path = _path(key).with_name(f"{key}.pages.json")
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def pages_or_extract(key: str, filename: str) -> List[Dict]:
    """Cached pages, or extract once with nyayavedika.ocr and cache them."""
    pages = get_pages(key)
    if pages is None:
        from . import ocr
        pages = ocr.extract(get(key), filename)
        put_pages(key, pages)
    return pages


def text_of(pages: List[Dict]) -> str:
    return "\n\n".join(p["text"] for p in pages).strip()
