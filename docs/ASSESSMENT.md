# NyayaVedika product-scope assessment

Assessment of the existing codebase against `NYAYAVEDIKA — Complete Product Scope & Code Implementation Instructions.md`.
This is Phase 1 only; product-code changes belong to later phases.

## Architecture and reusable implementation

- One FastAPI application in `server.py`, with shared services under `nyayavedika/` and static vanilla JavaScript/HTML under `static/`.
- Role authorization is centralized in `nyayavedika/auth.py`. Existing roles are `citizen`, `lawyer`, and `staff`; `lawyer` is the advocate role for this product. API routes are checked against `auth.POLICY`, and `tests/test_foundation.py` checks route-policy coverage and a cross-role matrix.
- The document pipeline already provides native PDF text extraction, OCR fallback, page-tagged text, content-addressed storage, extracted-page caching, document analysis, and source-grounded summaries (`nyayavedika/ocr.py`, `storage.py`, `agents/document_analyst.py`, `summarise.py`).
- Section 12 legal-aid eligibility and Section 479 BNSS checks are deterministic (`nyayavedika/legal_aid.py`, `triage.py`). The latter is covered by `tests/gold_479.json`.
- Tavily integration already exists in `nyayavedika/websearch.py`, with a configurable allowlist of trusted domains. The agent tool registry exposes `web_search`; the legal-aid question flow searches its existing legal-aid resources and can consult official web sources.
- The Court Staff UI and APIs already implement Today, Intake, Docket, Cause List, Undertrial, Document Summary, and Insights. These should be retained and improved in place.
- The separate `backend-case-pdf-main` tree is an independent product with a browser PDF workspace/tools and a Node OCR service. Per the NyayaVedika scope, treat it as a feature reference only; do not integrate or claim reuse of its source code.

## Scope-to-code map

| Scope | Existing implementation | Gap / implementation note |
|---|---|---|
| Three-door landing and navigation | `static/index.html` links to Citizen and combined Staff/Lawyer portals. | Add a distinct Advocate entry and route/UI while retaining the existing role model and staff screens. |
| Citizen legal-problem assistance | Citizen page currently has Legal Aid, Document Summary, and Rights tabs. The conversational agents can use legal-aid tools and official web search. | No dedicated natural-language legal-problem workflow was found that extracts the requested structured facts, identifies missing jurisdiction, generates two distinct formulations, executes both searches, deduplicates/filters results, and returns a sourced structured answer. Reuse Tavily; do not build a new legal database. |
| Section 12 Legal Aid Assistant | `/api/legal-aid`, `/explain`, `/ask`, `/application.docx`, existing legal-aid resources and citizen UI. | Preserve deterministic eligibility and application generation. Avoid adding application tracking. |
| Citizen Document Summary | `/api/documents/summarize` is available to all roles; it uses the shared extraction/OCR path and `summarise.summarise_pages`, which makes one document-reading call when the LLM is available and labels extractive fallback. | Existing implementation substantially matches the requested simple summary. Verify page references, missing-information behavior, progress/error states, and rights-tab invariance during later implementation. |
| Rights & Legal Information | `/legal-info`, `/api/legal-aid/topics`, and the Rights tab source entries from `legal_info.html`. | Frozen by scope. Do not change its content, data source, logic, API, or UI unless compatibility requires it. |
| Advocate Document Studio | No Advocate portal or PDF-editing endpoints/UI found in NyayaVedika. The existing OCR path only extracts text from PDFs. | Implement the requested merge/split/reorder/rotate/remove/OCR/bookmark/index/page-number operations using the existing shared backend where practical. The separate CasePDF app is a reference, not an integration source. |
| Advocate AI Document Insights | `/api/documents/analyze` runs the existing full Document Analyst and supports page-level OCR/extraction, grounding checks, and cached page text. | No advocate-selectable Issues/Facts/Case Background/Summarization mode was found. Analysis currently produces a broad brief on upload rather than generating only the selected insight. Reuse cached extracted pages; add mode-specific generation and tests. |
| Advocate document confidentiality | Role-level guards permit staff/lawyers to use document analysis; the analyzer stores documents by content hash and writes analysis to the shared document database. The page-source route is available to court roles. | The current static role token identifies a shared `demo-lawyer` actor, not an individual advocate. Resource-level owner/tenant authorization is therefore not established. Design and test per-resource isolation before exposing an Advocate workspace; do not rely on UI hiding. |
| Court Staff operations | All seven required modules are present in `static/staff.html` and backed by routes/services in `server.py` and `nyayavedika/`. | Preserve the modules and deterministic workflows. Regression-test intake/OCR, docket, scheduling, Section 479 alerts, summaries, and metrics; do not add another court module. |
| Shared backend and role policy | One FastAPI backend, a central route policy, role-aware agent tools, and static role tokens. | Extend `auth.POLICY` and add a full cross-role denial matrix for every new route. Role checks exist, but user/resource-level isolation needs additional design. |
| Configuration and deployment | `nyayavedika/config.py` reads a required root `.env`; Dockerfile and Compose files exist. | `.env.example` is absent although setup documentation instructs users to copy it. No `.env` is present, so the app/tests cannot initialize in this checkout. Add a safe, documented template and verify Docker/Azure startup in the integration/deployment phase. |

## Assessment risks and blockers

1. **Runtime/test setup:** `python -m unittest discover -s tests` ran 43 tests and ended with 28 import errors because `nyayavedika/envfile.py` requires a root `.env`, which is absent. This contradicts the test comments and setup documentation that describe an offline test run and `.env.example` template.
2. **Version control workflow:** neither the workspace root nor either project directory is a Git repository. The project instruction to use branch `v2-three-doors` and commit each phase cannot be followed in this checkout.
3. **Advocate isolation:** current credentials are shared static role tokens, not individual user identities. A distinct Advocate UI alone cannot satisfy advocate-to-advocate confidentiality. A stable authenticated owner identity and server-side resource ownership checks are required before storing Advocate documents.
4. **Live integrations:** no root `.env` is available, so configured Azure OpenAI and Tavily operation cannot be verified here. Implementations must explicitly report unavailable services rather than return invented research or analysis.
5. **Scope conflict resolution:** the product instructions mention CasePDF as a reference and explicitly prohibit claiming source integration. Follow that more specific implementation constraint; keep the two applications separate.

## Recommended implementation sequence

1. **Phase 1 — Assessment (this phase):** map existing architecture and gaps; record blockers and this plan.
2. **Phase 2 — Platform/navigation:** add three clear landing entries and role-specific navigation; keep the existing token checks and Court Staff portal.
3. **Phase 3 — Citizen Door:** add the structured legal-problem extraction and missing-jurisdiction follow-up; generate and execute two distinct live searches; filter and cite actual results. Preserve Legal Aid and Rights. Regression-test the one-call document summary.
4. **Phase 4 — Advocate Door:** provide a distinct lawyer-role experience; implement the scoped PDF tools and four on-demand insights; cache extracted/OCR text; implement server-side resource ownership before document persistence or retrieval.
5. **Phase 5 — Court Staff Door:** make only in-scope improvements to the seven existing modules and add focused regression tests; preserve Sections 12 and 479 deterministic logic.
6. **Phase 6 — Integration:** wire the portals to the shared backend, enforce role and per-resource permissions, audit consequential actions, and verify shared document-processing behavior.
7. **Phase 7 — Verification/deployment:** provide a safe `.env.example`, resolve offline test initialization, run the full suite and role-denial matrix, exercise real user flows, and verify Docker/Azure startup. Do not change `legal_info.html` or Rights behavior.

Each later phase should start with the tests relevant to its files, add tests for new behavior, and append its outcome/blockers to `docs/PROGRESS.md`. Keep the explicit out-of-scope list binding: no legal-aid tracking, CRM/client management, calendar, drafting assistant, separate advocate research module, payments, marketplace, video consultation, or extra Court Staff module.
