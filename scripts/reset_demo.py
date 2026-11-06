"""One-command demo reset: migrate, seed (fixed seed), make sure the legal-aid knowledge and sample files exist.

    python scripts/reset_demo.py [--url sqlite:///demo.db] [--size 120] [--seed 42]

Uses DATABASE_URL (from .env) unless --url is given. Re-running replaces the synthetic rows only:
uploaded cases are kept. Works on Windows, macOS and Linux (scripts/reset_demo.sh just calls this).
"""
import argparse
import sys
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

# nyayavedika.config reads .env on import.


def main(argv=None):
    from nyayavedika import config
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--url", help="database URL (default: DATABASE_URL)")
    ap.add_argument("--size", type=int, default=config.DEMO_SEED_CASES, help="synthetic cases (default DEMO_SEED_CASES = 120)")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--today", type=date.fromisoformat, default=date.today())
    a = ap.parse_args(argv)

    import seed_demo
    from nyayavedika import legal_aid_kb

    print("1/4 migrate + seed (seed %d, %d cases, anchor %s) ..." % (a.seed, a.size, a.today))
    counts = seed_demo.run(a.size, a.seed, a.today, a.url)
    print("    ", ", ".join(f"{k}={v}" for k, v in counts.items()))

    print("2/4 legal-aid knowledge ...")
    kb = Path(legal_aid_kb.DUMP)
    if not kb.exists():  # build the local keyword index from the bundled files (no Pinecone needed)
        r = legal_aid_kb.ingest(ROOT / "LEGAL_AID_DATA_FOR_IMPROVEMENTS", kb, html_files=(legal_aid_kb.LEGAL_INFO_HTML,))
        print(f"     built {r['chunks']} passages ({r['legal_info_entries']} from legal_info.html)")
    print("    local fallback file present:" if kb.exists() else "    MISSING local fallback file:", kb)

    print("3/4 sample documents ...")
    folder = ROOT / "sample_docs"
    if not list(folder.glob("*.txt")) or not list(folder.glob("*.pdf")):
        import make_sample_docs
        make_sample_docs.main() if hasattr(make_sample_docs, "main") else None
    print("    ", len(list(folder.glob("*.*"))), "files in sample_docs/")

    print("4/4 access tokens: set these in .env (one different long random value per role):")
    for role in ("STAFF", "LAWYER", "CITIZEN"):
        name = f"DEMO_TOKEN_{role}"
        value = getattr(config, name)
        print(f"     {name:20s} {'set' if value else 'NOT SET'}")
    tokens = [getattr(config, f"DEMO_TOKEN_{r}") for r in ("STAFF", "LAWYER", "CITIZEN")]
    if len(set(t for t in tokens if t)) < len([t for t in tokens if t]):
        print("     WARNING: two roles share a token; the first role wins, so one role is unreachable.")
    print("\nDone. Start with:  python server.py   (the intake worker runs inside it)")


if __name__ == "__main__":
    main()
