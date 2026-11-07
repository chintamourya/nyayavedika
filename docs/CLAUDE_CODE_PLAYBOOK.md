# Playbook: building NyayaVedika v2 with Claude Code

## Setup
1. Unzip your repo, `git init` if needed, `git checkout -b v2-three-doors`.
2. Copy CLAUDE.md to the repo root and docs/*.md into docs/.
3. Put CasePDF in reference/casepdf/ and add `reference/` to .gitignore. Check its LICENSE.
4. Run `claude` in the repo root. Start phases 0 and 1 in plan mode (Shift+Tab). `/clear` between phases.

## Decisions to make BEFORE phase 1 (the repo forces them)
1. Advocate vs lawyer. Today the `lawyer` role shares /staff with court staff and is the only role allowed to approve Sec.479 release applications (POST /api/alerts/decide). SCOPE gives the Advocate door only two features. Recommended: new /advocate page with Document Studio and AI Insights; leave the approval endpoint and the Undertrial module working as they are.
2. Per-user isolation. auth.py has one static token per role, so two advocates are indistinguishable and "advocate documents isolated" cannot be true. Recommended: allow several tokens per role (e.g. DEMO_TOKEN_LAWYER_1, _2), derive owner_id from the token, and key stored documents and extraction caches by (owner_id, sha256). storage.py is content-addressed today, so identical files from different users collide.
3. Citizen "No login" on the landing page vs RBAC. Keep citizen as a token-less or shared-token role, and say so honestly in the README.

## Phase prompts (paste each, after /clear)
**0. Assessment (plan mode, no code changes)**
Read CLAUDE.md and docs/SCOPE.md. Use the Explore agent to map the repo. Write docs/ASSESSMENT.md: per-portal modules, a table mapping every SCOPE feature to exists / improve / missing, reusable pieces (ocr.py, extraction.py, websearch.py, agents/front_door.py, document_analyst.py), RBAC gaps, risks, phase plan. Change no code.

**1. Three doors and RBAC**
Implement SCOPE sections 6.1 and 6.4. New landing with three doors (Citizen, Advocate, Court Staff); add static/advocate.html; remove the "staff and lawyers" merge. Resolve decisions 1 and 2 above as recommended. Every route in auth.POLICY; backend tests that each role is denied the others' routes and that advocate A cannot read advocate B's documents. Keep feedback wall working.

**2. Citizen: Describe Your Legal Problem**
Extend agents/front_door.py and websearch.py, do not build a new stack. Flow: one structured extraction call, then two differently worded queries, both run through websearch, dedupe, rank official domains (indiacode.nic.in, sci.gov.in, *.gov.in, nalsa.gov.in, High Court sites), flag conflicts, then a grounded answer. Return sources with title, organisation, URL, retrieval date, jurisdiction. If search returns nothing reliable, say so. A claim with no source is marked "unverified". Tests mock the search client and assert no URL appears that is not in the results. Leave Legal Aid logic and the Rights tab untouched.

**3. Citizen: Document Summary and Legal Aid polish**
Make Citizen Document Summary one LLM call over page-tagged text, plain language, page references, "not stated in the document" where missing. Use the existing extraction and OCR pipeline. Section 12 stays deterministic; only fix real bugs; run tests/legal_aid_cases.json.

**4. Court Staff (do before Advocate: it is your strongest rubric story)**
Preserve the seven modules. Improve: Sec.479 monitoring (edge cases: multiple cases, life/death offences, first-offender one-third, date arithmetic; extend gold_479.json), docket prioritisation (show the score breakdown in the UI), cause list (hard guarantee against double-booking a bench, advocate or case, with tests), Today and Insights metrics consistent with each other. Do not add modules.

**5. Advocate: Document Studio**
Server-side with pypdf and pypdfium2 (already in requirements). Order: merge, split, OCR to a searchable PDF (pytesseract image_to_pdf_or_hocr), page numbers, bookmarks, clickable index; then rotate, reorder, remove. Page thumbnails via pypdfium2. Size and page limits with clear errors. Check reference/casepdf LICENSE before copying anything; otherwise reimplement.

**6. Advocate: AI Document Insights**
Upload once; extract/OCR once and cache pages by (owner, sha256) via storage.put_pages. Four on-demand insights (Issues, Facts, Case Background, Summarization), each a separate call generated only when chosen and cached per document and type. Every item carries page references and is labelled "stated" or "inferred". Add the faded "Multi-document insights, coming soon" button, disabled, with no handler.

**7. Impact, tests, deploy**
Extend impact.py and audit.py events (documents processed, undertrials flagged, applications generated, eligibility checks, insights generated), no PII. Add a staff metrics view and CSV export. Update README and SUBMISSION.md numbers from docs/PROBLEM_STATS.md. Run the full suite, build the Docker image, verify startup. Report blockers honestly.

## Fix before you submit
- Numbers disagree: README says 5.8 crore pending and 4.34 lakh undertrials; PROBLEM_STATS says 5.9 crore and 4,03,302. Pick the sourced figures and update README and SUBMISSION.md.
- README still has DEMO_LINK_HERE, VIDEO_LINK_HERE and CLOUD_HERE.
- Proven impact (25 points) is empty. The app already has impact_events, pilot_report.py and pilot/pilot_log_template.csv. Run a small real pilot (legal aid clinic, paralegals, law students) and report real counts, however small. Never mix in simulation numbers.
- gold_479.json is "not yet lawyer-verified". Get one advocate to review it.
- Confirm the AgentFoundry eligibility rule (see below).
