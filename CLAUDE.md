# NyayaVedika (existing FastAPI + vanilla JS app, MIT)
Extend, never rewrite. Read docs/SCOPE.md and docs/ASSESSMENT.md (once it exists) before any task.
Goal: win "Timely Justice" (docs/RUBRIC.md). Quality of solution and proven impact matter most.

## Repo map
server.py (all routes) · nyayavedika/auth.py (POLICY role matrix; roles staff/lawyer/citizen) · agents/ (LangGraph; front_door.py = citizen chat, document_analyst.py) ·
websearch.py (Tavily, trusted domains) · ocr.py / extraction.py / storage.py (content-hash storage, page cache) · triage.py (Sec.479 + scoring) · legal_aid.py (Sec.12) ·
cause_list.py / scheduler.py · impact.py / audit.py · static/{index,citizen,staff}.html · tests/ (run offline, no keys) · legal_info.html (Rights, FROZEN).

## Hard rules
- Do not modify legal_info.html or the Rights tab logic/content.
- Sec.12 eligibility and Sec.479 logic stay deterministic code. Never the LLM. Keep tests/gold_479.json passing.
- No fabricated legal citations or URLs; every cited URL must come from a real search result.
- Every new route gets an entry in auth.POLICY and a cross-role denial test. UI hiding is not security.
- "advocate" in SCOPE.md = the existing `lawyer` role. Do not add a fourth role.
- Secrets only in .env; update .env.example; never print or commit keys. Keep Azure Container Apps deploy working (Dockerfile, docker-compose).
- SCOPE.md section 9 (out of scope) is binding, including under other names.
- No mock data in product paths. Do not claim synthetic numbers are field results.

## Workflow
- One phase per session. Run `python -m unittest discover -s tests` before saying done; add tests for new logic.
- Append to docs/PROGRESS.md after each phase: changes, files, endpoints, blockers.
- Commit per phase on branch v2-three-doors.
