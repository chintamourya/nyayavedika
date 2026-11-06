"""Score extraction + summarisation on sample_docs/ against sample_docs/ground_truth (no database needed).

    python scripts/eval_samples.py [--dir sample_docs]

Prints one line per file and the accuracy line. Files this machine cannot read (PDF without pypdf, scans
without Tesseract) are listed as skipped, with the reason - they are not counted as right or wrong.
"""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import extraction, llm, ocr, store, summarise  # noqa: E402

FIELDS = ("case_type", "stage", "filing_date", "accused_in_custody", "custody_since", "act", "section")


def evaluate(folder: Path = ROOT / "sample_docs") -> dict:
    db = store.connect("sqlite://")  # in-memory: only statute_ref is needed
    store.prepare_database(db)
    rows, skipped, right, total, unverified = [], [], 0, 0, []
    for gt_path in sorted((folder / "ground_truth").glob("*.json")):
        gt = json.loads(gt_path.read_text(encoding="utf-8"))
        try:
            pages = ocr.extract((folder / gt["file"]).read_bytes(), gt["file"])
            if not "".join(p["text"] for p in pages).strip():
                raise ValueError("no text (scanned page needs Tesseract OCR)")
        except Exception as exc:
            skipped.append(f"{gt['file']}: {exc}")
            continue
        doc_type = summarise.classify_doc_type(pages)
        draft, engine = extraction.extract(pages, doc_type)
        fields, _, _ = extraction.normalise(draft, gt["file"], db=db)
        out = summarise.summarise_pages(pages, doc_type)
        wrong = [f for f in FIELDS if fields.get(f) != gt[f]]
        right += len(FIELDS) - len(wrong)
        total += len(FIELDS)
        unverified += [f"{gt['file']}: {u}" for u in out["verification"]["unverified"]]
        rows.append(f"{gt['file']:34s} type={doc_type:12s} wrong={wrong} plan={out['plan']} "
                    f"unverified={len(out['verification']['unverified'])}")
    db.close()
    n = len(rows)
    engine = "llm+rules" if llm.available() else "rules + extractive"
    line = (f"Extraction accuracy: {right}/{total} fields ({100 * right / total:.0f}%) on {n} of {n + len(skipped)} "
            f"sample files [{engine}]; verifier: {len(unverified)} unverified dates/sections") if total else "nothing readable"
    return {"rows": rows, "skipped": skipped, "line": line, "right": right, "total": total, "unverified": unverified}


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=str(ROOT / "sample_docs"))
    result = evaluate(Path(ap.parse_args().dir))
    print("\n".join(result["rows"]))
    for s in result["skipped"]:
        print(f"skipped  {s}")
    print(result["line"])
