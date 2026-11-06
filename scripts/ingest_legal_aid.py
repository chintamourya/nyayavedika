"""Index the legal-aid knowledge file(s) - ready to run.

    python scripts/ingest_legal_aid.py                                   # LEGAL_AID_DATA_FOR_IMPROVEMENTS/ + legal_info.html
    python scripts/ingest_legal_aid.py path/to/folder [--dump data/legal_aid_kb.json] [--no-legal-info]
    python scripts/ingest_legal_aid.py --query "am I eligible for a free lawyer"   # check what the guide will find

Reads every .txt / .md file in the folder (blocks marked ########<source>############) and the curated legal_info.html page
(LEGAL_INFO_HTML; one chunk per entry, each with its official sources and checked date), chunks them, writes the
local JSON dump used for offline keyword search, and upserts to Pinecone (namespace PINECONE_LEGALAID_NAMESPACE,
hosted embeddings) when PINECONE_API_KEY is set in .env. Safe to re-run: chunk ids are content hashes.
The 5-question guide and the chat search this index (Pinecone first, the local dump otherwise).
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, legal_aid_kb, vectorstore  # noqa: E402

DEFAULT_FOLDER = ROOT / "LEGAL_AID_DATA_FOR_IMPROVEMENTS"


def show(query: str, top_k: int = 4) -> None:
    r = legal_aid_kb.search(query, top_k)
    print(f"\nQuery: {query}\nEngine: {r['engine']}")
    for i, p in enumerate(r["passages"], 1):
        print(f"  [{i}] {p['heading'] or '-'} ({p['authority']}) {p['source_url']}\n      {p['text'][:160]!r}")
    if not r["passages"]:
        print("  (no passages - run the ingest first)")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("folder", nargs="?", default=str(DEFAULT_FOLDER), help="folder with the legal-aid source file(s)")
    ap.add_argument("--dump", default=str(legal_aid_kb.DUMP))
    ap.add_argument("--query", help="only search the index and print the passages (no ingest)")
    ap.add_argument("--no-legal-info", action="store_true", help="skip legal_info.html")
    a = ap.parse_args()
    if a.query:
        show(a.query)
        sys.exit(0)
    folder = Path(a.folder)
    if not folder.is_dir():
        sys.exit(f"Folder not found: {folder}")
    if not vectorstore.available():
        print("Pinecone is not configured (PINECONE_API_KEY not set or pinecone SDK missing): writing the local "
              "dump only. The guide will use keyword search over it.")
    html = () if a.no_legal_info else (legal_aid_kb.LEGAL_INFO_HTML,)
    if html and not legal_aid_kb.LEGAL_INFO_HTML.is_file():
        print(f"legal_info.html not found at {legal_aid_kb.LEGAL_INFO_HTML} (LEGAL_INFO_HTML): indexing the folder only.")
    result = legal_aid_kb.ingest(folder, Path(a.dump), html_files=html)
    print(json.dumps({**result, "namespace": config.PINECONE_LEGALAID_NAMESPACE,
                      "index": config.PINECONE_LEGALAID_INDEX or config.PINECONE_INDEX}, indent=2))
    show("am I eligible for a free lawyer")
    show("police refused to register my FIR")
