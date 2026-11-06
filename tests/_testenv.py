"""Offline settings for the test-suite. Import this FIRST in a test file, before anything from `nyayavedika`.

Settings still come from the project's .env (the only settings file). This module only overrides the handful of
values a test run must not take from it, in memory, so tests never use live API keys, the live database or the
network, and never depend on values you tune in .env for production:
  * every API key / access token blank, NYAYAVEDIKA_OFFLINE on, a local SQLite file instead of the real database;
  * the few tunables that the assertions were written against (pinned below).
Nothing here is shipped to production: tests/ is excluded from the Docker image and from the release zip.
"""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from nyayavedika import envfile  # noqa: E402

envfile.OVERRIDES.update({
    # no network, no secrets, no live database
    "NYAYAVEDIKA_OFFLINE": "1",
    "AZURE_OPENAI_API_KEY": "",
    "AZURE_OPENAI_ENDPOINT": "",
    "PINECONE_API_KEY": "",
    "PINECONE_INDEX": "nyayavedika",
    "PINECONE_LEGALAID_INDEX": "",
    "TAVILY_API_KEY": "",
    "DATABASE_URL": "sqlite:///nyayavedika_dev.db",
    "CHECKPOINT_DB_URI": "",
    "NYAYAVEDIKA_CHECKPOINTER": "memory",
    "DEMO_TOKEN_STAFF": "",
    "DEMO_TOKEN_LAWYER": "",
    "DEMO_TOKEN_CITIZEN": "",
    # tunables the assertions were written against
    "AZURE_OPENAI_DEPLOYMENT": "test-deployment",
    "AGING_CAP": "25",
    "ALLOWED_EXTS": "pdf,txt",
    "LLM_MAX_RETRIES": "1",
    "MAP_PART_TOKENS": "3000",
    "SINGLE_PASS_TOKENS": "12000",
    "DEMO_MAX_FILES": "5",
    "DEMO_MAX_FILE_MB": "50",
})
