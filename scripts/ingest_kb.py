"""Build the legal knowledge base in Pinecone from a folder of PDFs / text files.

    python scripts/ingest_kb.py --dir kb/law --namespace law --source "India Code"
    python scripts/ingest_kb.py --dir kb/judgments --namespace judgments --source "Supreme Court of India"

Suggested free, official sources (download manually, check each site's terms):
  law:       India Code bare acts - BNS 2023, BNSS 2023, BSA 2023, Legal Services Authorities Act 1987,
             NI Act 1881, PWDV Act 2005, CPC 1908 (Order XVII, Sec. 89); NALSA schemes and SOPs
  judgments: Supreme Court / High Court judgments on undertrial release, bail, legal aid
"""
import argparse
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from nyayavedika import ocr, vectorstore  # noqa: E402
from nyayavedika.documents import generate_file_id  # noqa: E402

SECTION_RE = re.compile(r"^\s*(?:Section\s+)?(\d{1,4}[A-Z]?)\.\s+[A-Z]", re.M)


def chunk_statute(text: str, max_chars: int = 2500):
    """Prefer section boundaries so each passage is citable; fall back to fixed windows."""
    starts = [m.start() for m in SECTION_RE.finditer(text)]
    if len(starts) < 3:
        return [(None, text[i:i + max_chars]) for i in range(0, len(text), max_chars - 300)]
    starts.append(len(text))
    out = []
    for a, b in zip(starts, starts[1:]):
        body = text[a:b].strip()
        sec = SECTION_RE.match(body)
        for j in range(0, len(body), max_chars):
            out.append((sec.group(1) if sec else None, body[j:j + max_chars]))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", required=True)
    ap.add_argument("--namespace", default="law", choices=["law", "judgments"])
    ap.add_argument("--source", default="")
    args = ap.parse_args()
    if not vectorstore.available():
        sys.exit(f"Pinecone unavailable: {vectorstore.status()['reason']}")
    total = 0
    for path in sorted(Path(args.dir).glob("**/*")):
        if path.suffix.lower() not in (".pdf", ".txt") + ocr.IMAGE_EXTS:
            continue
        data = path.read_bytes()
        pages = ocr.extract(data, path.name)
        text = "\n".join(p["text"] for p in pages)
        doc_id = generate_file_id(data)[:12]
        records = [{"id": f"{doc_id}-{i}", "text": chunk, "title": path.stem, "source": args.source or path.stem,
                    "section": sec or "", "url": ""} for i, (sec, chunk) in enumerate(chunk_statute(text)) if chunk.strip()]
        total += vectorstore.upsert_chunks(args.namespace, records)
        print(f"{path.name}: {len(records)} passages")
    print(f"Done - {total} passages in namespace '{args.namespace}'")


if __name__ == "__main__":
    main()
