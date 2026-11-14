"""Legal-aid knowledge index: explains procedures and rights, with citations.

    python scripts/ingest_legal_aid.py LEGAL_AID_DATA_FOR_IMPROVEMENTS

Source file format: blocks opened and closed by marker lines such as
    ########https://example.org/page############   ...text...   ########https://example.org/page############
    ########NALSA############                       (a bare name; a URL inside the block is used when present)
Each block keeps its source URL and an authority tag: primary (NALSA / government) or secondary (articles).
Chunks follow headings (~800 tokens, 100 overlap, heading kept); ids are content hashes, so re-runs are safe.
Pinecone namespace PINECONE_LEGALAID_NAMESPACE (index PINECONE_LEGALAID_INDEX, else the default index);
a local JSON dump (data/legal_aid_kb.json) backs a keyword search when Pinecone is not configured.
The index explains; it never decides eligibility (legal_aid.check_eligibility does).

legal_info.html (repo root, setting LEGAL_INFO_HTML) is a second source: a curated page of short entries
(<article class="kbe" id=...>: an <h2> title, bullet facts, a "Law:" line and official source links each with the
date it was checked). Each entry becomes one chunk with its own sources, so answers about FIRs, RTI, arrest rights,
legal aid, Lok Adalat, consumer and cyber complaints, domestic violence, maintenance, wages, cheque bounce, helplines,
etc. cite the official page.

"""
import hashlib
import json
import math
import re
from collections import Counter
from datetime import date
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Dict, List, Optional
from urllib.parse import urlparse

from . import config, vectorstore

ROOT = Path(__file__).resolve().parents[1]
DUMP = ROOT / "data" / "legal_aid_kb.json"
MARKER = re.compile(r"^\s*#{4,}\s*(.+?)\s*#{4,}\s*$")
CHUNK_TOKENS, OVERLAP_TOKENS = 800, 100
PRIMARY_HOSTS = ("nalsa.gov.in", "gov.in", "nic.in", "sci.gov.in", "rbi.org.in", "s3waas.gov.in", "tele-law.in")
LEGAL_INFO_HTML = ROOT / config.LEGAL_INFO_HTML if not Path(config.LEGAL_INFO_HTML).is_absolute() \
    else Path(config.LEGAL_INFO_HTML)
LEGAL_INFO_CREDIT = "legal_info.html (legal information page)"
TOPICS = [  # first match wins; order = most specific first
    ("lok_adalat", r"lok adalat"),
    ("helpline", r"helpline|15100|toll[- ]free"),
    ("arrested_rights", r"arrest|custody|police station|remand|undertrial"),
    ("supreme_court", r"supreme court legal services committee|sclsc"),
    ("eligibility", r"eligib|entitled|section 12|income|scheduled caste|woman|child|disab"),
    ("procedure", r"apply|application|procedure|how to|form|affidavit|online"),
]
STATES = ["Andhra Pradesh", "Telangana", "Karnataka", "Tamil Nadu", "Kerala", "Maharashtra", "Delhi", "Uttar Pradesh",
          "Bihar", "West Bengal", "Gujarat", "Rajasthan", "Odisha", "Punjab", "Haryana", "Assam", "Madhya Pradesh"]


def tokens(text: str) -> int:
    return len(text) // 4 + 1


# ----------------------------------------------------------------------------- parse
def _source_url(label: str, body: str) -> str:
    if label.lower().startswith("http"):
        return label
    m = re.search(r"https?://\S+", body[:600])
    return m.group(0).rstrip(".,)") if m else f"source: {label}"


def authority(url: str, label: str = "") -> str:
    host = urlparse(url).netloc.lower() if url.startswith("http") else ""
    if label.upper() == "NALSA" or any(host == h or host.endswith("." + h) for h in PRIMARY_HOSTS):
        return "primary"
    return "secondary"


def parse_blocks(text: str) -> List[Dict]:
    """[{label, source_url, authority, text}] - one per marked block; text outside blocks is ignored."""
    blocks, current, lines = [], None, []
    for line in text.splitlines():
        m = MARKER.match(line)
        if not m:
            if current is not None:
                lines.append(line)
            continue
        label = m.group(1).strip()
        if current is not None and label == current:  # closing marker
            body = "\n".join(lines).strip()
            if body:
                url = _source_url(label, body)
                blocks.append({"label": label, "source_url": url, "authority": authority(url, label), "text": body})
            current, lines = None, []
        else:  # opening marker (an unclosed previous block is closed implicitly)
            if current is not None and "\n".join(lines).strip():
                body = "\n".join(lines).strip()
                url = _source_url(current, body)
                blocks.append({"label": current, "source_url": url, "authority": authority(url, current), "text": body})
            current, lines = label, []
    return blocks


# ----------------------------------------------------------------------------- chunk
def _is_heading(line: str) -> bool:
    s = line.strip()
    return 3 <= len(s) <= 90 and not s.endswith((".", ",", ";", ":")) and (s.endswith("?") or s[0].isupper()) \
        and len(s.split()) <= 12 and not s.startswith(("(", "•", "-"))


def _sections(text: str) -> List[Dict]:
    secs, heading, buf = [], "", []
    lines = [l for l in text.splitlines() if l.strip()]
    for i, line in enumerate(lines):
        nxt = lines[i + 1].strip() if i + 1 < len(lines) else ""
        # a wrapped PDF line is followed by a lowercase continuation; a real heading by a new sentence
        if _is_heading(line) and (line.strip().endswith("?") or not nxt or nxt[0].isupper() or nxt[0].isdigit()):
            if buf:
                secs.append({"heading": heading, "text": "\n".join(buf)})
                buf = []
            heading = line.strip()
        else:
            buf.append(line.strip())
    if buf:
        secs.append({"heading": heading, "text": "\n".join(buf)})
    return secs


def topic_of(text: str) -> str:
    low = text.lower()
    return next((t for t, pat in TOPICS if re.search(pat, low)), "general")


def chunk_block(block: Dict, verified: Optional[str] = None) -> List[Dict]:
    """Heading-led chunks of <= CHUNK_TOKENS; a long section continues with ~OVERLAP_TOKENS of overlap."""
    verified = verified or date.today().isoformat()
    out = []
    for sec in _sections(block["text"]):
        words, start = sec["text"].split(), 0
        step_words = (CHUNK_TOKENS - OVERLAP_TOKENS) * 3 // 4  # ~0.75 words per token
        size_words = CHUNK_TOKENS * 3 // 4
        while start < len(words):
            body = " ".join(words[start:start + size_words])
            heading = sec["heading"] + (" (continued)" if start else "")
            text = f"{heading}\n{body}".strip() if heading else body
            states = [s for s in STATES if s.lower() in text.lower()]
            out.append({"id": hashlib.sha256(f"{block['source_url']}|{text}".encode()).hexdigest()[:24],
                        "text": text, "heading": sec["heading"], "source_url": block["source_url"],
                        "authority": block["authority"], "topic": topic_of(text), "state": ", ".join(states) or "all India",
                        "last_verified": verified})
            if start + size_words >= len(words):
                break
            start += step_words
    return out


# ----------------------------------------------------------------------------- legal_info.html
class _LegalInfoHtml(HTMLParser):
    """Collects <article class="kbe"> entries: title, facts, meta lines and checked sources."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.entries: List[Dict] = []
        self.cur: Optional[Dict] = None
        self.field: Optional[str] = None   # "title" | "fact" | "meta" | "src"
        self.buf: List[str] = []
        self.in_src = False
        self.href = ""

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        cls = (a.get("class") or "").split()
        if tag == "article" and "kbe" in cls:
            self.cur = {"id": a.get("id") or "", "title": "", "facts": [], "meta": [], "sources": []}
        elif self.cur is None:
            return
        elif tag == "h2":
            self._start("title")
        elif tag == "ul" and "src" in cls:
            self.in_src = True
        elif tag == "li":
            self._start("src" if self.in_src else "fact")
            self.href = ""
        elif tag == "p" and "meta" in cls:
            self._start("meta")
        elif tag == "a" and self.field == "src" and not self.href:
            self.href = a.get("href") or ""

    def _start(self, field):
        self.field, self.buf = field, []

    def handle_data(self, data):
        if self.field:
            self.buf.append(data)

    def handle_endtag(self, tag):
        if self.cur is None:
            return
        text = re.sub(r"\s+", " ", unescape("".join(self.buf))).strip()
        if tag == "h2" and self.field == "title":
            self.cur["title"], self.field = text, None
        elif tag == "li" and self.field in ("fact", "src"):
            if self.field == "fact" and text:
                self.cur["facts"].append(text)
            elif self.field == "src" and self.href:
                checked = re.search(r"checked (\d{4}-\d{2}-\d{2})", text)
                note = text.replace(self.href, "", 1).strip(" –-")
                note = re.sub(r"\s*checked \d{4}-\d{2}-\d{2}\s*$", "", note).strip(" –-")
                self.cur["sources"].append({"url": self.href, "note": note,
                                            "checked": checked.group(1) if checked else None})
            self.field = None
        elif tag == "p" and self.field == "meta":
            if text:
                self.cur["meta"].append(text)
            self.field = None
        elif tag == "ul" and self.in_src:
            self.in_src = False
        elif tag == "article":
            if self.cur["title"] and self.cur["facts"]:
                self.entries.append(self.cur)
            self.cur, self.field = None, None


def parse_legal_info_html(html: str) -> List[Dict]:
    """[{id, title, facts[], meta[], sources[{url, note, checked}]}] - one per <article class="kbe">."""
    p = _LegalInfoHtml()
    p.feed(html)
    p.close()
    return p.entries


def legal_info_chunks(html: str, verified: Optional[str] = None) -> List[Dict]:
    """One chunk per legal_info.html entry (entries are short); cites its first official source, lists all of them."""
    out = []
    for e in parse_legal_info_html(html):
        srcs = e["sources"]
        url = srcs[0]["url"] if srcs else f"source: {LEGAL_INFO_CREDIT}"
        checked = max((s["checked"] for s in srcs if s.get("checked")), default=None) or verified \
            or date.today().isoformat()
        text = "\n".join([e["title"]] + ["- " + f for f in e["facts"]] + e["meta"])
        primary = bool(srcs) and all(authority(s["url"]) == "primary" for s in srcs)
        states = [s for s in STATES if s.lower() in text.lower()]
        out.append({"id": hashlib.sha256(f"legal_info.html|{e['id']}|{text}".encode()).hexdigest()[:24],
                    "text": text, "heading": e["title"], "source_url": url,
                    # list[str]: Pinecone metadata cannot hold objects
                    "sources": [f"{s['url']} - {s['note'] or 'official page'}"
                                + (f" (checked {s['checked']})" if s.get("checked") else "") for s in srcs],
                    "authority": "primary" if primary else "secondary", "topic": e["id"] or topic_of(text),
                    "state": ", ".join(states) or "all India", "last_verified": checked,
                    "collection": "legal_info.html", "credit": LEGAL_INFO_CREDIT})
    return out


# ----------------------------------------------------------------------------- ingest + search
def ingest(folder: Optional[Path], dump: Path = DUMP, verified: Optional[str] = None,
           html_files: tuple = ()) -> Dict:
    """Index the marked .txt/.md files in `folder`, plus any legal_info.html-style pages (in the folder or `html_files`)."""
    files = sorted(p for p in Path(folder).glob("*") if p.is_file() and p.suffix.lower() in (".txt", ".md")) \
        if folder else []
    pages = [Path(h) for h in html_files if Path(h).is_file()]
    if folder:
        pages += sorted(p for p in Path(folder).glob("*.html") if p.is_file())
    chunks = []
    for f in files:
        for block in parse_blocks(f.read_text(encoding="utf-8", errors="replace")):
            chunks += chunk_block(block, verified)
    kb_entries = 0
    for page in dict.fromkeys(pages):
        got = legal_info_chunks(page.read_text(encoding="utf-8", errors="replace"), verified)
        kb_entries += len(got)
        chunks += got
    unique = list({c["id"]: c for c in chunks}.values())
    dump.parent.mkdir(parents=True, exist_ok=True)
    dump.write_text(json.dumps(unique, ensure_ascii=False, indent=1), encoding="utf-8")
    indexed = vectorstore.upsert_chunks(config.PINECONE_LEGALAID_NAMESPACE, unique,
                                        index_name=config.PINECONE_LEGALAID_INDEX or None)
    return {"files": len(files) + len(set(pages)), "chunks": len(unique), "legal_info_entries": kb_entries,
            "indexed_in_pinecone": indexed, "primary": sum(c["authority"] == "primary" for c in unique),
            "dump": str(dump)}


_WORD = re.compile(r"[a-z0-9]+")
_STOP = set("the a an of to in and or is are for on by with what who how can be it this that as at from i my me do".split())


def _terms(text: str) -> List[str]:
    return [w for w in _WORD.findall(text.lower()) if w not in _STOP and len(w) > 1]


def _rank_documents(query: str, docs: List[Dict], top_k: int) -> List[Dict]:
    q = _terms(query)
    df = Counter(t for d in docs for t in set(_terms(d["text"])))
    n = len(docs) or 1
    lengths = {id(d): len(_terms(d["text"])) for d in docs}
    avg = sum(lengths.values()) / n or 1
    scored = []
    for d in docs:
        tf = Counter(_terms(d["text"]))
        heading_terms = set(_terms(d.get("heading", "")))
        s = sum((1 + math.log(tf[t])) * math.log(1 + n / df[t]) * (2 if t in heading_terms else 1) for t in q if tf[t])
        s /= 0.6 + 0.4 * lengths[id(d)] / avg   # length normalisation (BM25-style): long passages do not win on volume
        if s > 0 and heading_terms:  # prefer the entry whose title is mostly the question ("Lok Adalat" over "Permanent ...")
            s *= 1 + len(heading_terms & set(q)) / len(heading_terms | set(q))
        if s > 0:
            scored.append((s * (1.2 if d["authority"] == "primary" else 1.0), d))
    scored.sort(key=lambda x: -x[0])
    return [{**d, "score": round(s, 3)} for s, d in scored[:top_k]]


def _local_search(query: str, top_k: int, dump: Path) -> List[Dict]:
    if not dump.exists():
        return []
    return _rank_documents(query, json.loads(dump.read_text(encoding="utf-8")), top_k)


def search_legal_info(query: str, top_k: int = 2, html_path: Optional[Path] = None) -> List[Dict]:
    """Search the current legal_info.html entries so callers can use updates without re-indexing."""
    path = Path(html_path) if html_path else LEGAL_INFO_HTML
    if not path.is_file():
        return []
    docs = legal_info_chunks(path.read_text(encoding="utf-8", errors="replace"))
    hits = _rank_documents(query, docs, top_k)
    return [{"text": h["text"][:2000], "heading": h.get("heading"), "source_url": h.get("source_url"),
             "authority": h.get("authority"), "topic": h.get("topic"), "last_verified": h.get("last_verified"),
             "sources": list(h.get("sources") or [])[:5], "collection": "legal_info.html",
             "citation": f"{h.get('source_url')} ({h.get('authority')}, checked {h.get('last_verified')})"}
            for h in hits]


def topics(html_path: Optional[Path] = None) -> Dict:
    """Every legal_info.html entry for the citizen "Know your rights" list: title, facts, law lines and checked sources.
    Read straight from the page, so editing legal_info.html changes the list without a re-index (the search needs one)."""
    path = Path(html_path) if html_path else LEGAL_INFO_HTML
    if not path.is_file():
        return {"topics": [], "count": 0, "credit": LEGAL_INFO_CREDIT, "note": f"{path.name} not found"}
    out = []
    for e in parse_legal_info_html(path.read_text(encoding="utf-8", errors="replace")):
        out.append({"id": e["id"], "title": e["title"], "facts": e["facts"], "meta": e["meta"],
                    "sources": e["sources"],
                    "authority": "primary" if e["sources"] and all(authority(s["url"]) == "primary" for s in e["sources"])
                    else "secondary"})
    return {"topics": out, "count": len(out), "credit": LEGAL_INFO_CREDIT,
            "checked": max((s["checked"] for t in out for s in t["sources"] if s.get("checked")), default=None),
            "disclaimer": "Legal information, not legal advice. Free legal aid helpline 15100; emergency 112."}


def search(query: str, top_k: int = 4, dump: Path = DUMP) -> Dict:
    """Passages with citations; primary sources first among equals; flags reliance on secondary sources."""
    hits = vectorstore.search(config.PINECONE_LEGALAID_NAMESPACE, query, top_k,
                              index_name=config.PINECONE_LEGALAID_INDEX or None) if vectorstore.available() else []
    engine = "pinecone" if hits else "keyword (local)"
    if not hits:
        hits = _local_search(query, top_k, dump)
    hits.sort(key=lambda h: (h.get("authority") != "primary", -h.get("score", 0)))
    passages = [{"text": h["text"][:2000 if h.get("collection") == "legal_info.html" else 1200], "heading": h.get("heading"), "source_url": h.get("source_url"),
                 "authority": h.get("authority"), "topic": h.get("topic"), "last_verified": h.get("last_verified"),
                 "sources": list(h.get("sources") or [])[:5], "collection": h.get("collection") or "legal_aid.txt",
                 "citation": f"{h.get('source_url')} ({h.get('authority')}, checked {h.get('last_verified')})"} for h in hits]
    note = None
    if passages and all(p["authority"] != "primary" for p in passages):
        note = "These passages come from secondary sources (articles), not NALSA or government text - confirm with the DLSA."
    return {"query": query, "engine": engine, "passages": passages, "secondary_only_note": note,
            "disclaimer": "Legal information, not legal advice. Helpline 15100."}
