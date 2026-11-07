# NyayaVedika — complete code map and how the project works

This repository is a legal-tech workflow for Indian courts and legal-aid access. In plain terms, it helps:

- citizens check whether they may qualify for free legal aid,
- staff and lawyers triage incoming court cases,
- staff upload legal documents and turn them into structured case records,
- the system schedule hearings and draft cause lists,
- undertrial release alerts are identified and reviewed,
- a chat/assistant can answer procedural and legal-aid questions with grounded evidence,
- a demo dashboard shows intake, docket, scheduling, and impact reporting.

The project is built around a FastAPI backend, a Postgres/SQLite data layer, LangGraph agents, offline rules when no LLM is available, and a static HTML/JS front end.

---

## 1) What the project is

The main product is a “court operations + citizen access” system built around the problem of legal backlog and undertrial delay in India.

From the README and code:

- it is designed to help legal-aid workers, registry staff, judges, and citizens,
- it manages incoming court documents and case files,
- it scores and prioritizes cases by urgency,
- it drafts and explains release/eligibility steps,
- it uses human approval before any action with legal consequences,
- it records metrics and audit events for impact tracking.

The project is deliberately hybrid: deterministic rules decide legal thresholds, while LLMs are used mainly for summarization, drafting, and explanation. The key legal rules are not left entirely to an LLM.

---

## 2) High-level architecture

The codebase is arranged into these major layers:

1. Front end (static HTML/JS)
   - [static/index.html](./static/index.html)
   - [static/citizen.html](./static/citizen.html)
   - [static/staff.html](./static/staff.html)
   - [static/common.js](./static/common.js)
   - [static/citizen.js](./static/citizen.js)
   - [static/staff.js](./static/staff.js)

2. Web API server
   - [server.py](./server.py)

3. Business logic and rules engine
   - [nyayavedika/triage.py](./nyayavedika/triage.py)
   - [nyayavedika/legal_aid.py](./nyayavedika/legal_aid.py)
   - [nyayavedika/scheduler.py](./nyayavedika/scheduler.py)
   - [nyayavedika/cause_list.py](./nyayavedika/cause_list.py)
   - [nyayavedika/undertrial_watch.py](./nyayavedika/agents/undertrial_watch.py)

4. Data access and persistence
   - [nyayavedika/db_schema.py](./nyayavedika/db_schema.py)
   - [nyayavedika/store.py](./nyayavedika/store.py)
   - [nyayavedika/db.py](./nyayavedika/db.py)

5. Intake / document processing pipeline
   - [nyayavedika/intake.py](./nyayavedika/intake.py)
   - [nyayavedika/ocr.py](./nyayavedika/ocr.py)
   - [nyayavedika/extraction.py](./nyayavedika/extraction.py)
   - [nyayavedika/documents.py](./nyayavedika/documents.py)
   - [nyayavedika/summarise.py](./nyayavedika/summarise.py)
   - [nyayavedika/summarizer.py](./nyayavedika/summarizer.py)
   - [nyayavedika/worker.py](./nyayavedika/worker.py)

6. Agent system and conversation layer
   - [nyayavedika/agents](./nyayavedika/agents)
   - [nyayavedika/agents/front_door.py](./nyayavedika/agents/front_door.py)
   - [nyayavedika/agents/react.py](./nyayavedika/agents/react.py)
   - [nyayavedika/agents/document_analyst.py](./nyayavedika/agents/document_analyst.py)
   - [nyayavedika/agents/registry.py](./nyayavedika/agents/registry.py)

7. AI and retrieval infrastructure
   - [nyayavedika/llm.py](./nyayavedika/llm.py)
   - [nyayavedika/vectorstore.py](./nyayavedika/vectorstore.py)
   - [nyayavedika/websearch.py](./nyayavedika/websearch.py)
   - [nyayavedika/legal_aid_kb.py](./nyayavedika/legal_aid_kb.py)

8. Operational support and demo utilities
   - [nyayavedika/auth.py](./nyayavedika/auth.py)
   - [nyayavedika/audit.py](./nyayavedika/audit.py)
   - [nyayavedika/impact.py](./nyayavedika/impact.py)
   - [nyayavedika/demo_seed.py](./nyayavedika/demo_seed.py)
   - [nyayavedika/feedback.py](./nyayavedika/feedback.py)
   - [scripts](./scripts)
   - [data](./data)

---

## 3) How the app starts

The application starts from [server.py](./server.py).

Key startup flow:

- it creates a FastAPI app,
- it runs a startup lifecycle via `lifespan()`,
- it initializes the database with `db.engine()`,
- it sets up the LangGraph checkpoint store,
- it validates role tokens,
- it calls `store.prepare_database()` to ensure the tables exist and migrations are applied,
- it seeds synthetic demo data if the case table is empty,
- it starts the inline intake worker thread in-process.

The app exposes a very large set of API routes, and the code layers requests into storage, rules, agents, and document processing.

---

## 4) Configuration and environment model

The project treats `.env` as the single source of truth.

Important files:

- [nyayavedika/config.py](./nyayavedika/config.py)
- [nyayavedika/envfile.py](./nyayavedika/envfile.py)

How it works:

- config reads `.env` before any settings are used,
- keys are declared in one place for the whole app,
- missing required variables cause a clear startup error,
- a missing LLM key does not crash the app; the app falls back to offline rules.

The configuration covers:

- Azure OpenAI credentials and deployments,
- PostgreSQL/SQLite database URLs,
- Pinecone vector index settings,
- Tavily web-search settings,
- Tesseract OCR settings,
- legal-aid thresholds and helpline values,
- triage weights and scheduling parameters,
- demo mode and demo seed sizes,
- upload limits and file types.

The code explicitly says it is designed so that no secrets are embedded in source code.

---

## 5) Database and schema

The central schema is in [nyayavedika/db_schema.py](./nyayavedika/db_schema.py).

The app can use:

- PostgreSQL for real deployment, or
- SQLite for local/dev work.

The schema includes tables such as:

- `courts`
- `benches`
- `court_calendar`
- `case_type_ref`
- `stage_ref`
- `statute_ref`
- `cases`
- `advocates`
- `case_advocates`
- `hearings`
- `documents`
- `document_analyses`
- `ingest_batches`
- `ingest_jobs`
- `triage_scores`
- `case_queue_state`
- `listings`
- `alerts`
- `legal_aid_requests`
- `impact_events`
- `field_feedback`

The schema supports:

- case metadata and triage score history,
- document storage and OCR/analysis snapshots,
- queue states for intake jobs,
- scheduling outputs,
- undertrial alerts,
- legal-aid requests,
- event logs for reporting.

The repository layer [nyayavedika/store.py](./nyayavedika/store.py) normalizes database operations and provides helper methods for case retrieval, insert/update, queue state, and reference tables.

---

## 6) Security and role-based access

Security is implemented in [nyayavedika/auth.py](./nyayavedika/auth.py).

The app supports three demo roles:

- `staff`
- `lawyer`
- `citizen`

It uses bearer tokens from `.env`:

- `DEMO_TOKEN_STAFF`
- `DEMO_TOKEN_LAWYER`
- `DEMO_TOKEN_CITIZEN`

The code checks authorization on every API route with `guard("METHOD /path")` attached to server endpoints. This means the route policy is declared centrally instead of scattered across the app.

Examples:

- staff-only endpoints include docket, triage, impact export, and cause-list publishing,
- lawyer-only endpoints include alert decisions,
- citizens can use public/legal-aid routes and chat endpoints,
- some endpoints allow all roles or anonymous citizen when configured.

The app also logs audit actions through [nyayavedika/audit.py](./nyayavedika/audit.py).

---

## 7) Main user flows

### 7.1 Citizen portal

The citizen UI is [static/citizen.html](./static/citizen.html) and [static/citizen.js](./static/citizen.js).

It provides:

- language selection (English/Hindi/Telugu),
- a five-question legal-aid eligibility guide,
- an optional legal question flow with attached documents,
- a document summary tab for uploads,
- a rights/knowledge section for legal information.

The backend route group for this is in [server.py](./server.py):

- `POST /api/legal-aid`
- `POST /api/legal-aid/explain`
- `POST /api/legal-aid/ask`
- `POST /api/legal-aid/application.docx`
- `GET /api/legal-aid/topics`
- `GET /api/legal-aid/kb`
- `GET /api/legal-aid/state-fact`
- `POST /api/summarize/offline`
- `POST /api/agent/chat`

The legal-aid logic is governed by [nyayavedika/legal_aid.py](./nyayavedika/legal_aid.py), which uses deterministic rules for Sec. 12 eligibility, plus a knowledge base and web lookup for changing facts such as income limits.

### 7.2 Staff / lawyer portal

The staff UI is [static/staff.html](./static/staff.html) and [static/staff.js](./static/staff.js).

It provides tabs for:

- Today / operations board,
- Intake,
- Docket,
- Cause list,
- Document summary,
- Undertrial watch,
- Insights.

It interacts with APIs to:

- upload documents,
- create intake batches,
- read docket and case detail,
- prepare cause-list drafts,
- publish lists,
- review undertrial alert decisions,
- download reports and impacts.

### 7.3 Landing page and feedback wall

The landing page [static/index.html](./static/index.html) presents the product and includes feedback cards and a feedback form.

Feedback logic is in [nyayavedika/feedback.py](./nyayavedika/feedback.py) and the corresponding frontend in [static/feedback.js](./static/feedback.js).

The API exposes:

- `GET /api/field-feedback`
- `GET /api/field-feedback/all`
- `POST /api/field-feedback`
- `POST /api/field-feedback/{feedback_id}/hide`

This is not placeholder data; it is designed as a real field-feedback system.

---

## 8) Intake and document-processing pipeline

The intake pipeline is primarily in [nyayavedika/intake.py](./nyayavedika/intake.py) and the worker [nyayavedika/worker.py](./nyayavedika/worker.py).

### Intake modes

The app supports several intake modes:

- `separate` — each uploaded file becomes a separate case,
- `one_case` — multiple files are grouped into one case,
- `existing_case` — attach files to an existing case number,
- `by_folder` — each subfolder becomes a case,
- `summary_only` — summarise without creating a case.

The intake layer checks:

- file type,
- size and page count limits,
- duplicate or junk files,
- case-number patterns and folder grouping rules,
- whether a file already exists in the database.

### Queue and worker

Jobs are stored in the `ingest_jobs` queue table.

The worker does the actual analysis in stages:

- read / OCR / parse file,
- summarise content,
- extract structured information,
- score the case,
- transform the case into a docket entry,
- mark for review or propose a cause-list slot when needed.

The worker handles retries, stale jobs, concurrency, and failure reasons. It is designed to be safe when multiple workers run at once.

### OCR and extraction

The OCR path is in:

- [nyayavedika/ocr.py](./nyayavedika/ocr.py)
- [nyayavedika/extraction.py](./nyayavedika/extraction.py)
- [nyayavedika/documents.py](./nyayavedika/documents.py)

The project tries to accept PDF and text documents, and uses Tesseract where configured.

The extraction layer attempts to infer:

- case type,
- stage,
- parties,
- dates,
- custody status,
- section / act,
- sentence length,
- flags like undertrial, disability, first-time offender, etc.

A document analysis result is stored with per-page evidence and provenance, so the case detail screen can show the source page that supported each fact.

---

## 9) Triage and case scoring

The core ranking engine is [nyayavedika/triage.py](./nyayavedika/triage.py).

It performs several tasks:

- assigns a case type and default urgency,
- computes a stack of risk/priority points,
- assesses undertrial release eligibility under Sec. 479 BNSS,
- detects legal flags (time-bound law, custody fact missing, life-or-death offence, etc.),
- categorizes the case into a priority band such as `Critical`, `High`, `Medium`, or `Routine`,
- recommends a disposal route (ADR, mediation, legal aid, etc.)

The scoring engine is meant to be auditable: weights are explicit and can be tuned from configuration. It stores results to `triage_scores` with a `rules_version` so the docket can explain why a case was prioritized.

Some important legal decisions are deterministic and separate from the LLM:

- undertrial eligibility checks are not done by the model,
- legal grounds are reasoned through code,
- the LLM can explain or draft, but it is not the authority on the legal cutoff.

This is a deliberate design to reduce unsafe legal hallucination.

---

## 10) Undertrial release watch

The undertrial workflow is implemented in [nyayavedika/agents/undertrial_watch.py](./nyayavedika/agents/undertrial_watch.py).

This agent:

- scans custody cases,
- checks whether they are near or beyond the legal threshold,
- drafts a release application,
- stores a pending alert,
- waits for a lawyer approval,
- updates status after approval or dismissal.

The alert lifecycle is:

- `pending`
- `approved`
- `filed`
- `heard`
- `released` or `denied`
- `dismissed`

A dismissed case can be re-triggered only after a snooze period or a new custody fact update.

The release application is drafted using a template, with a legal-aid review requirement before filing.

---

## 11) Cause-list and scheduling logic

The scheduling logic is in:

- [nyayavedika/scheduler.py](./nyayavedika/scheduler.py)
- [nyayavedika/cause_list.py](./nyayavedika/cause_list.py)

What it does:

- sorts cases by urgency and batch,
- assigns them to benches based on case type and available time,
- estimates hearing duration using adjournment risk,
- avoids advocate conflicts,
- reserves capacity for urgent matters,
- calculates utilisation and unscheduled case reasons,
- provides a draft plan before publication.

This is a planning engine, not just a list-rendering template. It tries to make realistic, explainable hearing calendars rather than a simple FIFO queue.

---

## 12) Legal-aid knowledge and explanation engine

The legal-aid engine is in [nyayavedika/legal_aid.py](./nyayavedika/legal_aid.py), with knowledge search in [nyayavedika/legal_aid_kb.py](./nyayavedika/legal_aid_kb.py).

The workflow is:

- collect applicant facts,
- match them against Sec. 12 legal-aid categories,
- compute likely / possible / not-eligible outcomes,
- look up official legal-aid data (state income limits, helpline information),
- optionally use trusted web sources when local values are stale or missing,
- explain the result in plain language,
- draft an application when asked.

The system separates:

- “rules decide” (deterministic logic),
- “knowledge explains” (local knowledge base),
- “web facts confirm stale values” (official domains only),
- “LLM drafts wording” (not the legal decision itself).

This is a strong example of a safe rule-and-knowledge design.

---

## 13) Agent system and LangGraph

The project uses LangGraph-based agents under [nyayavedika/agents](./nyayavedika/agents).

Important files:

- [nyayavedika/agents/front_door.py](./nyayavedika/agents/front_door.py)
- [nyayavedika/agents/react.py](./nyayavedika/agents/react.py)
- [nyayavedika/agents/document_analyst.py](./nyayavedika/agents/document_analyst.py)
- [nyayavedika/agents/registry.py](./nyayavedika/agents/registry.py)
- [nyayavedika/agents/checkpoint.py](./nyayavedika/agents/checkpoint.py)
- [nyayavedika/agents/context.py](./nyayavedika/agents/context.py)
- [nyayavedika/agents/tools.py](./nyayavedika/agents/tools.py)

What they do:

- route incoming user message to the right type of task,
- choose a small set of tools,
- call legal-aid, case lookup, and document analysis tools,
- decide when to ask one missing fact before proceeding,
- use interrupt/resume behavior for human approval,
- keep thread state so a conversation can continue across turns.

The top-level AI layer is deliberately structured to ask clarifying questions rather than jump straight to a legal answer.

---

## 14) LLM, vector store, and web search

AI services are centralized in:

- [nyayavedika/llm.py](./nyayavedika/llm.py)
- [nyayavedika/vectorstore.py](./nyayavedika/vectorstore.py)
- [nyayavedika/websearch.py](./nyayavedika/websearch.py)

Summary:

- LLM provider is Azure OpenAI,
- a fallback backend can be injected for tests,
- the app supports an offline mode when keys are absent,
- the wrapper strips or masks personally identifying information before sending to a model when configured,
- the system stores legal knowledge and judgments in a vector database, and searches those when needed,
- official web search is used carefully and only for government/legal domains.

The app avoids all-to-LLM behavior: the legal threshold decisions remain in code.

---

## 15) Impact, audit, and demo metrics

Operational tracking happens in:

- [nyayavedika/impact.py](./nyayavedika/impact.py)
- [nyayavedika/audit.py](./nyayavedika/audit.py)
- [nyayavedika/pilot_metrics.py](./nyayavedika/pilot_metrics.py)

The project records events such as:

- legal-aid checks,
- case triage actions,
- undertrial alerts,
- scheduled cause-list runs,
- citizen sessions,
- all kinds of operational decisions.

This supports dashboard metrics and exports like `/api/impact` and `/api/impact/export.csv`.

---

## 16) Front-end mechanics

The front-end is intentionally plain JavaScript, no framework, no build tool.

Key shared utilities:

- [static/common.js](./static/common.js)

This file contains:

- token handling,
- API helper functions,
- file upload helpers,
- polling/progress UI behavior,
- band styling,
- file collection for uploads,
- download helpers.

The app uses form-based flows and vanilla DOM APIs, with many pages assembled directly from server JSON responses.

The front-end is designed to show the current role and token state, with a user able to switch between citizen and staff flows.

---

## 17) Scripts and operational utilities

The [scripts](./scripts) directory contains the project’s operational commands. Examples include:

- [scripts/check_env.py](./scripts/check_env.py) — validate environment configuration without exposing secrets.
- [scripts/dev_api.py](./scripts/dev_api.py) — start a demo API server on port 8010.
- [scripts/reset_demo.py](./scripts/reset_demo.py) — wipe and reseed demo data.
- [scripts/seed_demo.py](./scripts/seed_demo.py) — seed sample records.
- [scripts/import_docket.py](./scripts/import_docket.py) — import case data.
- [scripts/import_statutes.py](./scripts/import_statutes.py) — import statutes.
- [scripts/ingest_kb.py](./scripts/ingest_legal_aid.py) — legal-aid corpus and rule data ingestion.
- [scripts/ingest_legal_aid.py](./scripts/ingest_legal_aid.py) — legal-aid KB indexing.
- [scripts/make_release_zip.py](./scripts/make_release_zip.py) — package the app for release.
- [scripts/pilot_report.py](./scripts/pilot_report.py) — pilot metrics/report generation.
- [scripts/simulate_8_weeks.py](./scripts/simulate_8_weeks.py) — synthetic scenario run.
- [scripts/check_azure.py](./scripts/check_azure.py) — Azure connectivity checks.

These scripts are the project’s admin and demo glue.

---

## 18) Data and sample content

The repository includes:

- [data/legal_aid_kb.json](./data/legal_aid_kb.json)
- [data/sample_judgment.txt](./data/sample_judgment.txt)
- [data/statutes_template.csv](./data/statutes_template.csv)
- [sample_docs](./sample_docs)
- [LEGAL_AID_DATA_FOR_IMPROVEMENTS](./LEGAL_AID_DATA_FOR_IMPROVEMENTS)

The app is built around a demo/seeded legal-data environment. Sample docs are used for testing, evaluation, and user demonstration.

---

## 19) Tests and validation

The [tests](./tests) directory contains core automated checks for:

- agent flow,
- resilience,
- case handling,
- rule behavior,
- legal-aid and triage pathways.

The README says the suite can be run with:

```bash
python -m unittest discover -s tests
```

The tests are designed to run without network or API keys when the LLM backend is swapped out with scripted results.

---

## 20) Documentation and product explanation files

The repository has a set of supporting docs:

- [README.md](./README.md) — high-level product summary and quick start.
- [SUBMISSION.md](./SUBMISSION.md) — competition/problem narrative.
- [docs/SETUP.md](./docs/SETUP.md) — setup, env, API reference, and deployment notes.
- [docs/EVAL.md](./docs/EVAL.md) — evaluation notes.
- [docs/PILOT_GUIDE.md](./docs/PILOT_GUIDE.md) — pilot workflow.
- [docs/SIMULATION.md](./docs/SIMULATION.md) — simulation and synthetic metrics.
- [docs/UI_WALKTHROUGH.md](./docs/UI_WALKTHROUGH.md) — product walkthrough.
- [docs/DEMO_SCRIPT.md](./docs/DEMO_SCRIPT.md) — demo narration.
- [docs/CREDITS.md](./docs/CREDITS.md) — credits.

These explain the product, deployment, legal problem, and demo usage in more narrative form than the Python code does.

---

## 21) End-to-end system flow

This is the practical lifecycle of the system:

1. A user opens the citizen or staff portal.
2. The browser sends requests to the FastAPI server.
3. The server checks the bearer token and role policy.
4. If the request is upload-related, the intake layer validates the file and queues a job.
5. The worker processes the file in the background.
6. OCR/extraction summarise and extract case facts.
7. The case is triaged and scored based on rules and data.
8. The docket is updated, or a legal-aid output is generated.
9. The user can ask natural-language questions through the agent layer.
10. The agent chooses tools, reads local knowledge, uses web search if necessary, and answers with citations or guidance.
11. Undertrial alerts and cause-list plans trigger human approval before legal action.
12. Impact and audit logs record what happened.

This is the project’s core pattern: legal rules are explicit, human oversight remains central, and the LLM is used as a drafting/explaining layer rather than as the final legal authority.

---

## 22) Summary of the codebase in one sentence

NyayaVedika is a legal-tech operations platform that turns incoming court documents and citizen inquiries into structured cases, scored priorities, legal-aid decisions, undertrial alerts, and cause-list scheduling, while keeping legal thresholds deterministic and requiring human review for real legal actions.

---

## 23) Files worth reading first

If you want to understand the project quickly, read these in order:

1. [README.md](./README.md)
2. [server.py](./server.py)
3. [nyayavedika/config.py](./nyayavedika/config.py)
4. [nyayavedika/auth.py](./nyayavedika/auth.py)
5. [nyayavedika/db_schema.py](./nyayavedika/db_schema.py)
6. [nyayavedika/intake.py](./nyayavedika/intake.py)
7. [nyayavedika/triage.py](./nyayavedika/triage.py)
8. [nyayavedika/legal_aid.py](./nyayavedika/legal_aid.py)
9. [nyayavedika/worker.py](./nyayavedika/worker.py)
10. [nyayavedika/agents/front_door.py](./nyayavedika/agents/front_door.py)
11. [static/staff.html](./static/staff.html)
12. [static/citizen.html](./static/citizen.html)
13. [docs/SETUP.md](./docs/SETUP.md)

This list will give you the clearest understanding of both architecture and operational behavior.
