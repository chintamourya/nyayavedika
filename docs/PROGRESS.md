# Development progress

## Phase 1 — Codebase assessment

- **Status:** Complete; no product-code changes in this phase.
- **Changes:** Mapped the existing FastAPI backend, citizen flows, shared OCR/document pipeline, role policy, seven Court Staff modules, existing legal-aid and Section 479 logic, and the separate PDF reference application. Added [`ASSESSMENT.md`](./ASSESSMENT.md) with the feature map, gaps, risks, and phased implementation sequence.
- **Files:** `docs/ASSESSMENT.md`, `docs/PROGRESS.md`.
- **Endpoints:** No API changes.
- **Validation:** Ran `python -m unittest discover -s tests`; 43 tests ran, with 28 import errors because the required root `.env` is missing. No test assertions were reached for those modules.
- **Blockers:** `.env.example` is missing despite setup docs referencing it. Neither the workspace root nor project directories are Git repositories, so branch `v2-three-doors` and per-phase commits are unavailable. Individual advocate/resource isolation cannot be guaranteed with the current shared static role tokens; resolve identity/ownership before implementing Advocate document storage.

## Phase 2 — Platform and navigation

- **Status:** Implemented.
- **Changes:** Landing page now presents Citizen, Advocate, and Court Staff entry points. Added `/advocate` as a route to the existing shared staff application, with route-aware Advocate labeling and a client-side lawyer-role gate; backend API authorization remains unchanged. Removed the hard-coded demo-token example from the shared staff page and made the three-door layout responsive.
- **Files:** `static/index.html`, `static/styles.css`, `static/staff.html`, `static/staff.js`, `server.py`, `scripts/dev_api.py`, `tests/test_frontend.py`, `docs/SETUP.md`, `docs/PROGRESS.md`.
- **Endpoints:** Added public page route `GET /advocate` (serves the shared staff application). No API routes or role policies changed.
- **Validation:** `tests/test_frontend.py` passed (15 tests); JavaScript and Python syntax checks passed; route/link smoke checks passed. Full suite ran 332 tests (37 skipped) with 1 failure and 2 errors, all unrelated to Phase 2: `test_azure_backend_uses_configured_endpoint_version_and_deployment` expects a different configured model name; `test_pdf_over_page_limit_rejected_with_message` cannot import missing `pypdf`; `test_large_file_one_call_with_key_pages_under_the_token_cap` has no configured TPM limit (`input_budget()` is `None`).
- **Blockers:** Neither project folder is a Git repository, so no phase commit can be made. Advocate document storage/features and user-level document ownership are Phase 4 concerns; the `/advocate` screen remains backed only by existing role-authorized lawyer workflows.

## Phase 3 — Citizen Door

- **Status:** Implemented.
- **Changes:** Added a fourth Citizen capability to describe a legal problem. The backend extracts category, facts, parties, events, dates, jurisdiction, and the legal question; requests location when missing; generates two distinct searches; runs both through the existing Tavily integration; filters to HTTPS official-government domains and sufficiently relevant results; deduplicates results; and returns only source-linked claims with source excerpts and retrieval date. The Citizen UI supports location follow-up, loading/error/no-source states, escaped output, linked citations, and English/Hindi/Telugu strings. Legal Aid eligibility remains deterministic, and the Rights content/logic/data path was not changed.
- **Files:** `nyayavedika/legal_problem.py`, `nyayavedika/auth.py`, `server.py`, `scripts/dev_api.py`, `static/citizen.html`, `static/citizen.js`, `static/i18n.json`, `static/styles.css`, `tests/test_legal_problem.py`, `tests/test_foundation.py`, `tests/test_frontend.py`, `docs/SETUP.md`, `docs/PROGRESS.md`.
- **Endpoints:** Added `POST /api/legal-problem/research`, restricted to the existing citizen role (anonymous Citizen Door requests remain allowed). `server.py` and `scripts/dev_api.py` use the same service and explicit provider/input error handling.
- **Validation:** Research tests passed (6); frontend regression tests passed (16); role-policy tests passed (15, 5 skipped); JavaScript syntax and translation JSON checks passed. Full suite ran 339 tests (32 skipped), with 1 failure and 2 errors: existing Azure deployment-name expectation mismatch (`ignored-primary-model` vs `test-deployment`), missing `pypdf` for a PDF test, and missing TPM configuration causing `input_budget()` to return `None`. No Phase 3 test failed.
- **Blockers:** Live Azure OpenAI/Tavily operation cannot be verified without a successful provider response; the full run logged provider rate limits. The checkout is not a Git repository, so no phase commit can be created.

## Phase 4 — Advocate Door

- **Status:** Implemented; live provider integration and real advocate identity remain deployment limitations.
- **Changes:** Replaced the shared staff application at `/advocate` with a distinct Advocate portal. Added session-scoped, server-validated workspace capabilities; private PDF upload and cached page extraction/OCR; on-demand Issues, Facts, Case Background, or Summary insights with evidence/page validation; and an in-memory Document Studio supporting merge, split, reorder, rotate, page removal, OCR text export, bookmarks, clickable index, page numbering, and preview inspection. Advocate document IDs are excluded from the Court Staff page-source endpoint.
- **Files:** `nyayavedika/advocate.py`, `nyayavedika/document_studio.py`, `nyayavedika/db.py`, `nyayavedika/auth.py`, `nyayavedika/storage.py`, `server.py`, `scripts/dev_api.py`, `static/advocate.html`, `static/advocate.js`, `static/styles.css`, `tests/test_advocate.py`, `tests/test_document_studio.py`, `tests/test_foundation.py`, `tests/test_frontend.py`, `requirements.txt`.
- **Endpoints:** Added lawyer-only `POST /api/advocate/workspaces`, `/api/advocate/documents`, `/api/advocate/documents/{doc_id}/insights`, and `/api/advocate/studio`. Both `server.py` and `scripts/dev_api.py` use the same services and role policies.
- **Validation:** Advocate service tests passed (4); PDF Studio tests passed (5), covering workspace isolation, selected-only insights, unsupported evidence filtering, OCR reuse, all PDF operations, and invalid input handling.
- **Limitations:** The current shared lawyer token does not identify individual advocates. Workspace capabilities are unguessable and server-checked but only browser-session scoped. OCR output is a page-tagged text download, not a searchable PDF text layer.
- **Scope:** Phase 5 is intentionally skipped; no court workflow features were added.

## Phase 6 — Integration

- **Status:** Implemented; release readiness still requires real provider credentials, production database configuration, and advocate identity management.
- **Changes:** Kept both HTTP servers on the shared Advocate services and policies; documented routes and the workspace/OCR limitations; added a complete, secret-free offline/demo `.env.example`; and added cross-role checks for Advocate workspace separation and Court Staff source denial. Updated the stdlib-server route test to expect the new dedicated Advocate portal.
- **Validation:** Advocate service (4), PDF Studio (5), frontend (17), and HTTP workspace/privacy checks (1) passed. JavaScript syntax checks for all three portals and Python compilation checks passed. The broader foundation module still has an unrelated existing `/api/alerts` test error: the test SQLite schema lacks the `cases.source` column queried by `staff_api.alerts`; the focused Advocate HTTP test passes.
- **Deployment note:** `.env.example` is an offline/demo starter, not production scoring or Legal Aid configuration. Before deployment, set distinct strong role tokens, approved jurisdiction-specific triage/eligibility values, Azure/Tavily as required, PostgreSQL, and a durable checkpoint backend. Do not treat the shared lawyer token/workspace capability as per-person authentication.

## Follow-up — Shared local demo token

- **Status:** Implemented.
- **Changes:** A shared bearer token now resolves to the role selected by the current portal, while the endpoint policy still limits which roles each route accepts. Updated the local `.env` role tokens to `mourya` and removed a duplicate lawyer-token assignment; added a startup warning and documentation that a shared/short token grants all configured roles and is only suitable for an isolated local demo.
- **Files:** `.env`, `nyayavedika/auth.py`, `static/common.js`, `tests/test_auth_tokens.py`, `tests/test_foundation.py`, `tests/test_frontend.py`, `README.md`, `docs/SETUP.md`, `docs/PROGRESS.md`.
- **Endpoints:** No API routes or policy entries changed. The shared frontend API helper sends the active portal role through `X-Demo-Role`.
- **Validation:** Token tests passed (4); foundation tests passed (19, 7 skipped); frontend tests passed (17); JavaScript syntax and Python compilation checks passed. The full suite ran 353 tests (44 skipped) with 1 unrelated failure and 2 unrelated errors: Azure deployment-name expectation mismatch, missing `pypdf`, and missing TPM configuration. HTTP integration tests are skipped because FastAPI and LangGraph are not installed in this environment.
- **Limitations:** A shared `mourya` credential removes separation between staff, lawyer, and citizen access; replace it with distinct strong values before any deployment or use with real data. The checkout has no Git metadata, so the required phase commit cannot be created.

## Follow-up — Advocate Door UI/UX upgrade and PDF index fix

- **Status:** Implemented.
- **Changes:** Rebuilt the Advocate portal with its own stylesheet (light/dark theme, responsive, reduced-motion and print aware). Document Studio now uses operation cards, drag-and-drop upload, an ordered merge list, a page grid with click / Shift-click / odd / even / invert selection, drag-to-reorder, quick-fill helpers (volumes, bookmarks, index), client-side validation, and "Keep editing" to chain a result into the next operation. AI Document Insights shows four colour- and icon-distinct insight cards, a document card (pages, OCR pages), reuse of results already generated for the same document, collapsible sections, clickable page references that jump the preview, source-text toggle, filter, copy, save as text, print and regenerate. Fixed the clickable index: links now target the page object (a bare page index is only valid for remote links), which also fixes the failing studio test. Role header detection now ignores a trailing slash and the script version was bumped to avoid stale cached `common.js`.
- **Files:** `static/advocate.html`, `static/advocate.css` (new), `static/advocate.js`, `static/common.js`, `static/{staff,citizen}.html`, `nyayavedika/document_studio.py`.
- **Endpoints:** None added or changed; role policies unchanged.
- **Limitations:** Page thumbnails are numbered tiles, not rendered page images (no PDF renderer is bundled). Insight results cached in the browser are lost on reload; server-side extraction cache is unchanged.

## Follow-up — Impact on Timely Justice shown in the UI

- **Changes:** Added an "Impact on Timely Justice" panel to the Advocate page explaining how Document Studio and AI Document Insights reduce preparation delay, mapped to the four judging criteria, with real per-session counters (operations, pages, documents analysed, insights generated, insights reused, last insight time). Added a "How NyayaVedika cuts the backlog" section to the landing page (triage, summarisation, legal aid, scheduling, Studio, Insights), updated the Advocate door text, and added a short why-it-matters note to the Court Staff document summary.
- **Files:** `static/advocate.html`, `static/advocate.css`, `static/advocate.js`, `static/index.html`, `static/staff.html`, `static/styles.css`.
- **Evidence rules:** National figures come from `docs/PROBLEM_STATS.md` with source links. No field or time-saved figures are claimed; the counters are measured from the user's own session only.

## Follow-up — Azure OpenAI connection failures

- **Changes:** Restrict JSON-object fallback to explicit HTTP 400 rejections of JSON-schema response formatting. Network, timeout, deployment, authorization, and other failures now surface without an unnecessary second request. Advocate insights show actionable network/proxy guidance for Azure connection and timeout failures.
- **Files:** `nyayavedika/llm.py`, `nyayavedika/advocate.py`, `tests/test_llm_azure.py`, `tests/test_advocate.py`, `docs/PROGRESS.md`.
- **Endpoints:** No API routes changed.
- **Validation:** Focused Azure/Advocate tests passed (15). Full suite ran 357 tests and remains non-green with 5 failures, 3 errors, and 1 skipped; the new regressions pass. Existing failures include intake worker state expectations, a deployment-name assertion, and unrelated database/token-budget test errors.
- **Limitations:** DNS resolution and TCP/443 reachability work from this environment, but that does not verify Azure authentication, deployment availability, TLS/proxy behavior, or a full model request.
