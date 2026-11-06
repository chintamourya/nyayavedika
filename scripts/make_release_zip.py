"""Build a shareable zip of the project WITHOUT secrets or runtime data.

    python scripts/make_release_zip.py            -> dist/nyayavedika-release.zip

Excluded: every settings file (.env, .env.*, *.env), storage/, .git/, __pycache__/, *.db, kb/, dist/, .venv/.
Settings are never packaged: the target machine supplies its own .env (see README, "Deploying").
"""
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED_DIRS = {".git", "__pycache__", "storage", "kb", "dist", ".venv", "venv", "node_modules"}
EXCLUDED_SUFFIXES = (".db", ".pyc")


def should_include(relpath: str) -> bool:
    parts = Path(relpath.replace("\\", "/")).parts
    if any(p in EXCLUDED_DIRS for p in parts[:-1]):
        return False
    name = parts[-1]
    if name.startswith(".env") or name.endswith(".env") or name == "env.example":
        return False
    return not name.endswith(EXCLUDED_SUFFIXES)


def build(out: Path = ROOT / "dist" / "nyayavedika-release.zip") -> int:
    out.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(ROOT.rglob("*")):
            rel = path.relative_to(ROOT).as_posix()
            if path.is_file() and should_include(rel):
                zf.write(path, rel)
                count += 1
    print(f"Wrote {out} ({count} files; .env, storage/ and databases excluded)")
    return count


if __name__ == "__main__":
    build(Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "dist" / "nyayavedika-release.zip")
