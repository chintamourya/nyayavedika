"""Runtime configuration: one typed view of the settings. No secrets and no default values live here.

Every value comes from the .env file (nyayavedika/envfile.py) and nowhere else: not from the shell environment, not from literals in
the modules. A key missing from .env stops start-up with one error that lists all of them. This file is the complete list of
keys (one line each, with a comment); `.env.example` provides non-secret placeholders to copy into `.env`. Modules read
`config.NAME`; they never read the environment and never hardcode a tunable.
"""
import json  # noqa: F401  (kept: some callers import config.json-compatible helpers)

from . import envfile as _e

_e.load()  # before any setting below is read

S, I, F, B, L, J = _e.string, _e.integer, _e.number, _e.boolean, _e.items, _e.json_value

# --- LLM: Azure OpenAI (the only provider). Leave AZURE_OPENAI_API_KEY empty to run offline on rules. ---
AZURE_OPENAI_API_KEY = S("AZURE_OPENAI_API_KEY") or None
AZURE_OPENAI_ENDPOINT = S("AZURE_OPENAI_ENDPOINT")
AZURE_OPENAI_API_VERSION = S("AZURE_OPENAI_API_VERSION")
AZURE_OPENAI_DEPLOYMENT = S("AZURE_OPENAI_DEPLOYMENT")                 # reasoning / synthesis / agent
AZURE_OPENAI_FAST_DEPLOYMENT = S("AZURE_OPENAI_FAST_DEPLOYMENT")       # map steps, classification; empty = same as above
LLM_MAX_COMPLETION_TOKENS = I("LLM_MAX_COMPLETION_TOKENS")       # ceiling for one structured / reasoning call
LLM_REQUEST_TIMEOUT_SECONDS = F("LLM_REQUEST_TIMEOUT_SECONDS")
LLM_REASONING_EFFORT = S("LLM_REASONING_EFFORT")                 # reasoning deployments: minimal | low | medium | high (lower = faster; empty = model default)
LLM_CLIENT_MAX_RETRIES = I("LLM_CLIENT_MAX_RETRIES")             # the SDK's own transport retries

FORCE_OFFLINE = B("NYAYAVEDIKA_OFFLINE")
REDACT_BEFORE_LLM = B("NYAYAVEDIKA_REDACT")             # mask phone/email/Aadhaar/PAN first
AGENT_MAX_STEPS = I("NYAYAVEDIKA_AGENT_MAX_STEPS")
AGENT_FAST = B("NYAYAVEDIKA_AGENT_FAST")
AGENT_HISTORY_MESSAGES = I("NYAYAVEDIKA_AGENT_HISTORY_MESSAGES")
AGENT_MESSAGE_CHARS = I("NYAYAVEDIKA_AGENT_MESSAGE_CHARS")
AGENT_OBSERVATION_CHARS = I("NYAYAVEDIKA_AGENT_OBSERVATION_CHARS")
AGENT_JOB_POLL_SECONDS = F("NYAYAVEDIKA_AGENT_JOB_POLL_SECONDS")       # tools: wait between intake-batch status checks


# --- Database: PostgreSQL (SQLAlchemy + pg8000). SQLite for local dev only. ---------
def _normalize_db_url(url: str) -> str:
    """Accept a plain Supabase/libpq URL (postgresql:// or postgres://) and pin the pg8000 driver."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+pg8000://" + url[len("postgresql://"):]
    return url


DATABASE_URL = _normalize_db_url(S("DATABASE_URL"))
DATABASE_SSL_CA = S("DATABASE_SSL_CA")            # optional: path to the database CA .crt for full verification
DATABASE_LOCAL_HOSTS = L("DATABASE_LOCAL_HOSTS")  # hosts that are reached without TLS (local / compose network)
SQLITE_TIMEOUT_SECONDS = F("SQLITE_TIMEOUT_SECONDS")
DB_STATEMENT_TIMEOUT_MS = I("DB_STATEMENT_TIMEOUT_MS")           # raised for the big cause-list upsert
# LangGraph checkpointer: "postgres" or "memory" (tests / no-DB runs)
CHECKPOINTER = S("NYAYAVEDIKA_CHECKPOINTER")
CHECKPOINT_DB_URI = S("CHECKPOINT_DB_URI")        # libpq URI; if empty, derived from DATABASE_URL when Postgres
CHECKPOINT_POOL_SIZE = I("NYAYAVEDIKA_CHECKPOINT_POOL_SIZE")
CHECKPOINT_POOL_TIMEOUT_SECONDS = F("CHECKPOINT_POOL_TIMEOUT_SECONDS")
CHECKPOINT_CONNECT_TIMEOUT_SECONDS = F("CHECKPOINT_CONNECT_TIMEOUT_SECONDS")

# --- Vector DB: Pinecone (integrated hosted embeddings) --------
PINECONE_API_KEY = S("PINECONE_API_KEY") or None
PINECONE_INDEX = S("PINECONE_INDEX")
PINECONE_CLOUD = S("PINECONE_CLOUD")
PINECONE_REGION = S("PINECONE_REGION")
PINECONE_EMBED_MODEL = S("PINECONE_EMBED_MODEL")
PINECONE_UPSERT_BATCH = I("PINECONE_UPSERT_BATCH")                # integrated-embedding upserts cap at 96 per call
PINECONE_MAX_CHUNK_CHARS = I("PINECONE_MAX_CHUNK_CHARS")
NS_LAW = S("PINECONE_NS_LAW")                     # bare acts, NALSA schemes, legal-aid guides
NS_JUDGMENTS = S("PINECONE_NS_JUDGMENTS")         # precedent corpus
NS_CASEFILES = S("PINECONE_NS_CASEFILES")         # uploaded case documents (per-case filter by case_id)
PINECONE_LEGALAID_NAMESPACE = S("PINECONE_LEGALAID_NAMESPACE")
PINECONE_LEGALAID_INDEX = S("PINECONE_LEGALAID_INDEX")            # empty -> use PINECONE_INDEX
LEGAL_INFO_HTML = S("LEGAL_INFO_HTML")        # relative to the repo root

# --- Web search: Tavily ---------------------------------------------------------------------
TAVILY_API_KEY = S("TAVILY_API_KEY") or None
TAVILY_SEARCH_DEPTH = S("TAVILY_SEARCH_DEPTH")
WEBSEARCH_MAX_RESULTS = I("WEBSEARCH_MAX_RESULTS")
WEBSEARCH_CONTENT_CHARS = I("WEBSEARCH_CONTENT_CHARS")
TRUSTED_DOMAINS = L("NYAYAVEDIKA_TRUSTED_DOMAINS")      # agents may only search these official / authoritative domains

# --- OCR: Tesseract (Apache-2.0) -------------------------------------------------------------
TESSERACT_LANG = S("NYAYAVEDIKA_TESSERACT_LANG")        # add tel, tam, kan, mar, ben ... as installed
OCR_DPI = I("NYAYAVEDIKA_OCR_DPI")
OCR_LOW_CONFIDENCE = F("OCR_LOW_CONFIDENCE")      # mean word confidence below -> flag page
OCR_MIN_ALNUM_CHARS_PER_PAGE = I("OCR_MIN_ALNUM_CHARS_PER_PAGE")  # below this -> almost certainly image-only
OCR_MIN_CHARS_PER_PAGE_AREA = F("OCR_MIN_CHARS_PER_PAGE_AREA")    # alnum chars per pt^2 of page area
OCR_MIN_WORD_CONFIDENCE = F("OCR_MIN_WORD_CONFIDENCE")            # Tesseract word confidence (0-100) below which a word is dropped

# --- Domain settings ------------------------------------------------------------------------
LEGAL_AID_INCOME_LIMIT = I("NYAYAVEDIKA_LEGAL_AID_INCOME_LIMIT")        # Sec. 12(h) LSA Act ceiling, per State
MINUTES_PER_PAGE_READ = F("NYAYAVEDIKA_MINUTES_PER_PAGE")               # impact accounting
LEGAL_AID_HELPLINE = S("LEGAL_AID_HELPLINE")
LEGAL_AID_MAX_FOLLOWUPS = I("LEGAL_AID_MAX_FOLLOWUPS")
LEGAL_AID_MAX_QUESTION_DOCUMENTS = I("LEGAL_AID_MAX_QUESTION_DOCUMENTS")
LEGAL_AID_FOLLOWUP_SESSION_TTL_SECONDS = I("LEGAL_AID_FOLLOWUP_SESSION_TTL_SECONDS")
LEGAL_AID_MAX_TRACKED_SESSIONS = I("LEGAL_AID_MAX_TRACKED_SESSIONS")

# --- Triage / scheduling weights (judgement values, tune with registry feedback) ----------------
NEAR_THRESHOLD_PERCENT = I("NEAR_THRESHOLD_PERCENT")
CUSTODY_POINTS = I("CUSTODY_POINTS")
RELEASE_ELIGIBLE_POINTS = I("RELEASE_ELIGIBLE_POINTS")
NEARING_THRESHOLD_POINTS = I("NEARING_THRESHOLD_POINTS")
TRIAGE_POINTS = J("TRIAGE_POINTS")                # JSON object: age_per_year, age_cap, decade_years, ...
BAND_CUTS = J("BAND_CUTS")                        # JSON list of [band, minimum score], highest first
SLA_DAYS = J("SLA_DAYS")
DAY_START = tuple(int(x) for x in S("DAY_START").split(":")) if S("DAY_START") else (0, 0)      # "HH:MM"
_lunch = S("LUNCH").split("-") if S("LUNCH") else []                                            # "HH:MM-HH:MM"
LUNCH = tuple(tuple(int(x) for x in part.split(":")) for part in _lunch) if len(_lunch) == 2 else ((0, 0), (0, 0))
ADJOURNED_MINUTES = F("ADJOURNED_MINUTES")
CONFLICT_BUFFER_MINUTES = F("CONFLICT_BUFFER_MINUTES")
AGING_PER_DEFERRAL = I("AGING_PER_DEFERRAL")
AGING_PER_WEEK_LATE = I("AGING_PER_WEEK_LATE")
AGING_CAP = I("AGING_CAP")                        # max aging boost points
MUST_LIST_RESERVE = F("MUST_LIST_RESERVE")        # share of bench time kept for must-list
MUST_LIST_AFTER_DEFERRALS = I("MUST_LIST_AFTER_DEFERRALS")
SMOOTHING_K = I("ADJOURNMENT_SMOOTHING_K")
REGISTRY_MAX_REVIEW = I("REGISTRY_MAX_REVIEW")    # cases the review agent looks at per run
WEB_FACT_TTL_DAYS = I("WEB_FACT_TTL_DAYS")

# --- Demo build -------------------------------------------------------------------------------
DEMO_MODE = B("DEMO_MODE")
DEMO_STATE = S("DEMO_STATE")
DEMO_COURT_ID = S("DEMO_COURT_ID")
DEMO_SEED_CASES = I("DEMO_SEED_CASES")            # synthetic cases seeded into an empty docket
DEMO_MAX_FILES = I("DEMO_MAX_FILES")              # files per intake batch
DEMO_MAX_FILE_MB = I("DEMO_MAX_FILE_MB")          # per file
MAX_FILES_PER_FOLDER = I("MAX_FILES_PER_FOLDER")
ALLOWED_EXTS = [e.lower() for e in L("ALLOWED_EXTS")]
DEMO_MAX_PAGES = min(I("DEMO_MAX_PAGES_HARD_CAP"), I("DEMO_MAX_PAGES"))
STORAGE_DIR = S("STORAGE_DIR")                    # uploaded bytes keyed by content hash

# --- Worker / LLM budgets -------------------------------------------------------------------
WORKER_CONCURRENCY = I("WORKER_CONCURRENCY")
WORKER_MAX_ATTEMPTS = I("WORKER_MAX_ATTEMPTS")
WORKER_RETRY_BASE_SECONDS = I("WORKER_RETRY_BASE_SECONDS")        # 30 s, 2 min, 8 min ...
WORKER_STALE_MINUTES = I("WORKER_STALE_MINUTES")                  # no heartbeat -> back to queue
WORKER_POLL_SECONDS = F("WORKER_POLL_SECONDS")
WORKER_HEARTBEAT_SECONDS = F("WORKER_HEARTBEAT_SECONDS")
MAP_PARALLEL = I("MAP_PARALLEL")                  # map parts at once (free-tier limits)
REDUCE_GROUP = I("REDUCE_GROUP")                  # note sets merged per reduce call
LLM_CALLS_PER_MINUTE = I("LLM_CALLS_PER_MINUTE")  # per-process budget
LLM_MAX_RETRIES = I("LLM_MAX_RETRIES")            # on rate-limit errors
LLM_TPM_LIMIT = I("LLM_TPM_LIMIT")                # plan tokens-per-minute cap; 0 = no cap known
DOC_COMPLETION_TOKENS = I("DOC_COMPLETION_TOKENS")                # output reserve for the one document call
LLM_MAX_WAIT_SECONDS = F("LLM_MAX_WAIT_SECONDS")  # longest pause on a 429 before giving up
LLM_RETRY_BASE_SECONDS = F("LLM_RETRY_BASE_SECONDS")
EXTRACT_MIN_CONFIDENCE = F("EXTRACT_MIN_CONFIDENCE")              # below -> needs_review
MAP_PART_TOKENS = I("MAP_PART_TOKENS")
SINGLE_PASS_TOKENS = I("SINGLE_PASS_TOKENS")
DOC_ANALYST_MAX_ATTEMPTS = I("DOC_ANALYST_MAX_ATTEMPTS")
CHUNK_MAX_LINES = I("CHUNK_MAX_LINES")
CHUNK_OVERLAP_LINES = I("CHUNK_OVERLAP_LINES")
DOCX_FONT = S("DOCX_FONT")

# --- Access tokens (Authorization: Bearer <token>). Empty -> that role cannot sign in. -----
DEMO_TOKEN_STAFF = S("DEMO_TOKEN_STAFF")
DEMO_TOKEN_LAWYER = S("DEMO_TOKEN_LAWYER")
DEMO_TOKEN_CITIZEN = S("DEMO_TOKEN_CITIZEN")
ANONYMOUS_CITIZEN = B("ANONYMOUS_CITIZEN")        # a request with no token on a citizen endpoint acts as anonymous

# --- Server -----------------------------------------------------------------------------------
INLINE_WORKER = B("NYAYAVEDIKA_INLINE_WORKER")
HOST = S("NYAYAVEDIKA_HOST")
PORT = I("NYAYAVEDIKA_PORT")
DEV_API_HOST = S("DEV_API_HOST")
DEV_API_PORT = I("DEV_API_PORT")
SHUTDOWN_JOIN_SECONDS = F("SHUTDOWN_JOIN_SECONDS")
MAX_UPLOAD_BYTES = DEMO_MAX_FILE_MB * 1024 * 1024

_e.check()  # one error naming every missing / malformed key
