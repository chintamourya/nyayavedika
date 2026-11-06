# Setup, deployment and API reference

1. **Python 3.12 packages:** `pip install -r requirements.txt` (public PyPI).
2. **Tesseract** with language packs, e.g. `apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-tel`
   (Windows: the UB-Mannheim installer). Set `NYAYAVEDIKA_TESSERACT_LANG`.
3. **Postgres:** `docker compose up db`, or any Postgres 14+. Set `DATABASE_URL=postgresql+pg8000://…`.
4. **Settings and keys:** copy the template first: `cp .env.example .env`. Every setting lives in ONE file, `.env`, in the project root, and nowhere else: not the shell
   environment, not the code or the Docker image. `.env` is git-ignored; never commit it. `nyayavedika/config.py` reads it when it is imported and
   lists every key with a comment; a missing or malformed key stops start-up with one error naming all of them.
   Fill in `AZURE_OPENAI_API_KEY`, `AZURE_OPENAI_ENDPOINT` and `AZURE_OPENAI_DEPLOYMENT` (optionally
   `AZURE_OPENAI_FAST_DEPLOYMENT` for a smaller, quicker model on the reading and classification steps, `PINECONE_API_KEY`,
   `TAVILY_API_KEY`) and set three different long random `DEMO_TOKEN_*` values. Azure OpenAI is the only LLM provider.
   All keys may be empty: with none, the app runs offline on rules.
   Check the file any time with `python scripts/check_env.py` (prints key names only, never values).
   Index the legal-aid knowledge (files + `legal_info.html`): `python scripts/ingest_legal_aid.py`.
5. **Knowledge base:** put bare acts / NALSA PDFs in `kb/law` and judgments in `kb/judgments`, then run:
   ```bash
   python scripts/ingest_kb.py --dir kb/law --namespace law --source "India Code"
   ```
6. **Docket:**
   ```bash
   python scripts/import_docket.py --csv export.csv
   ```
   Use `--demo 600` instead for synthetic data. Without either, the server seeds the demo docket on first start.
7. **Run the server** (the intake worker starts inside it; set `NYAYAVEDIKA_INLINE_WORKER=0` to run `python -m nyayavedika.worker` yourself):
   ```bash
   python server.py
   ```
   Reset the demo data any time with `python scripts/reset_demo.py`. Then open http://127.0.0.1:8000. It has two front doors: `/staff` for court staff and lawyers (token) and `/citizen` for citizens (no login).
   The citizen portal pairs the eligibility check with optional cited legal questions and document uploads; both portals have a separate document-summary tab. Legal-aid questions search the local guide index first and consult trusted official web domains when no local passage is found. Limits are shown in the UI: at most 2 files per folder, 50 pages per file and 2 attachments per legal-aid question; each citizen legal-aid session allows 5 answered follow-up questions (eligibility checks do not count).
   Staff lists display at most 10 synthetic examples per data kind; this is display-only, so stored demo records, aggregate counts and scheduling actions are unchanged. Uploaded/imported records are not subject to this display cap.
   Schedule the nightly jobs as shown under "Background jobs".
8. **No FastAPI on the demo machine?** Run the stdlib demo server instead, then open http://127.0.0.1:8010:
   ```bash
   python scripts/dev_api.py
   ```
   It serves the same pages and role checks, the offline assistant, and an in-process worker. See `docs/UI_WALKTHROUGH.md` for the click-through.

Each integration degrades gracefully. With no Azure OpenAI key, agents fall back to offline rules. Without Pinecone,
search_law reports "unavailable" and the agent uses web_search. Without Tesseract, scanned pages are marked
as needing OCR.

## Deploying

The code you deploy contains **no settings and no secrets**. `.env` is excluded from git (`.gitignore`), from the Docker
image (`.dockerignore`) and from the release zip (`python scripts/make_release_zip.py`). Whatever runs the app must be given
its own `.env` at `/app/.env` (the project root):

- **docker compose:** `docker compose up --build` mounts `./.env` read-only into the app (see `docker-compose.yml`).
- **docker run:** `docker run -v /secure/path/.env:/app/.env:ro -p 8000:8000 <image>`.
- **hosting platforms:** use the platform's "secret file" feature and mount the file at `/app/.env`.
- **plain server:** copy `.env` to the project root with `chmod 600 .env`, then `python server.py`.

Before going live run `python scripts/check_env.py`. For a deployed service `.env` normally needs: `NYAYAVEDIKA_HOST=0.0.0.0`,
a PostgreSQL `DATABASE_URL`, `NYAYAVEDIKA_CHECKPOINTER=postgres`, and three different long random `DEMO_TOKEN_*` values.

## API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/agent/chat` | `{message, thread_id?, language?, agent: citizen\|staff}` → `{reply \| question, steps}` |
| POST | `/api/agent/resume` | Answer the agent's clarifying question: `{thread_id, answer}` |
| POST | `/api/documents/analyze` | `{filename, content_base64 \| text, case_id?, language}` |
| POST | `/api/documents/summarize` | `{filename, content_base64 \| text, language}`; one-off, not saved to a case |
| POST | `/api/undertrial/scan` | Run Undertrial Watch |
| GET/POST | `/api/alerts`, `/api/alerts/decide` | Review and approve release applications |
| POST | `/api/registry/run`, `/api/registry/decide` | Prepare and approve a cause list |
| POST | `/api/legal-aid`, `/api/legal-aid/{id}/outcome` | Eligibility check; partner reports the outcome |
| POST | `/api/legal-aid/ask` | `{question, language?, documents?}`; local legal-aid index first, official web fallback |
| GET | `/api/impact`, `/api/impact/export.csv` | Impact metrics and raw event log |
| POST | `/api/feedback` | Ratings 1–5 |

## Docket record fields

`case_id, court_id, case_type, filing_date, stage, adjournments, last_hearing_date, advocate_ids[],
accused_in_custody, custody_since, max_sentence_years, first_time_offender, senior_citizen, woman_or_child,
disability, legal_aid, act, section`. These match a CIS / NJDG export.

## Files, folders and the chat agent

- **Intake modes:** each file a separate case; *each sub-folder is one case* (`by_folder`); all files one case; attach to an existing case number; summary only (chat, no case created).
- A folder named like a case number (e.g. `SC-88-2024`) becomes that case. Other folder names are never used as case ids: the case id is generated.
- Junk files (`.DS_Store`, `Thumbs.db`, `~$` temp files, `__MACOSX`) are skipped and do not count toward the file cap. More than the cap is sent as several batches (staff screen) or kept to the first N with a warning (citizen chat).
- A file already in the system is reported as a duplicate and linked to its case; a failed file is re-queued when uploaded again. Jobs on the same case never run at the same time.
- When files are attached to a chat message the agent always reads them first. A question the agent asked is answered by the next message. Yes/No buttons appear only for confirmations and yes/no questions (`answer_kind` in the API reply).
- With no LLM configured, summaries are built from the extracted fields and say so; they are English only.
- Standalone citizen/staff summaries are not saved to a case. Citizens can explicitly attach a document to a legal-aid question; uploaded text is used only for that answer.
- `people_reached` counts chat sessions, not people, and figures from a demo or simulated database are not field results.

## Tests

```bash
python -m unittest discover -s tests
```

The agent-graph tests use a scripted LLM, so they need no keys or network. They skip automatically when
LangGraph or SQLAlchemy is not installed.

## Background jobs

Run the intake worker as its own process: `python -m nyayavedika.worker`.

The scheduled jobs can also be started from the staff UI with "Run now" (`POST /api/jobs/{name}/run`). Each run is
logged in `agent_runs`. Example crontab (server time; no cron is built into the app):

```
0 1 * * *    cd /app && python -m nyayavedika.jobs run undertrial_scan
30 1 * * *   cd /app && python -m nyayavedika.jobs run aging_update
0 16 * * 5   cd /app && python -m nyayavedika.jobs run weekly_cause_list
0 8 * * 1-5  cd /app && python -m nyayavedika.jobs run daily_topup
```

On Windows, use Task Scheduler with the same commands. The weekly list is only a draft: the Registrar approves it before anything is published.

## Using Supabase Postgres
Set `DATABASE_URL` in `.env` to your Supabase connection string (plain `postgresql://...` works; the app adds the
pg8000 driver and TLS automatically). URL-encode special characters in the password (`@` -> `%40`).
Tables are created on first start; LangGraph checkpoint tables are created in the same database.
