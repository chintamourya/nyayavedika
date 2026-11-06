"""Check the root .env before you deploy.   python scripts/check_env.py

Confirms every key the code reads is present and well-formed, then warns about values that usually mean "still set
up for a laptop". Prints key NAMES only, never values. Exit code 0 = ready, 1 = fix the errors listed.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import envfile  # noqa: E402

try:
    from nyayavedika import auth, config  # noqa: E402  (importing config validates every key)
except envfile.ConfigError as e:
    print(f"ERROR\n{e}")
    sys.exit(1)

warnings = []
if config.HOST in ("127.0.0.1", "localhost"):
    warnings.append("NYAYAVEDIKA_HOST is 127.0.0.1: a container or server will not be reachable from outside. Use 0.0.0.0.")
if config.DATABASE_URL.startswith("sqlite"):
    warnings.append("DATABASE_URL is SQLite: fine for local dev, not for a deployed service. Use PostgreSQL.")
if config.CHECKPOINTER == "memory":
    warnings.append("NYAYAVEDIKA_CHECKPOINTER=memory: agent conversations are lost on every restart. Use postgres to keep them.")
if config.FORCE_OFFLINE:
    warnings.append("NYAYAVEDIKA_OFFLINE is on: the LLM, Pinecone and web search are disabled.")
elif not (config.AZURE_OPENAI_API_KEY and config.AZURE_OPENAI_ENDPOINT and config.AZURE_OPENAI_DEPLOYMENT):
    warnings.append("AZURE_OPENAI_API_KEY / AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_DEPLOYMENT is empty: the app will run offline on rules only.")
if config.DEMO_MODE:
    warnings.append("DEMO_MODE is true: synthetic demo cases are seeded into an empty database.")
warnings += [f"Access tokens: {p}" for p in auth.token_problems()]
if not auth.configured_roles():
    warnings.append("No DEMO_TOKEN_* is set: every /api call except /api/health will return 401.")
placeholders = [k for k, v in envfile._values.items() if v.lower().startswith(("change-me", "replace-me"))]
if placeholders:
    warnings.append("Placeholder values still in .env for: " + ", ".join(sorted(placeholders)))

print(f"OK: {envfile.loaded_from()} has every key the code reads.")
for w in warnings:
    print(f"WARNING: {w}")
if not warnings:
    print("No deployment warnings.")
