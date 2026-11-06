# NyayaVedika (న్యాయవేదిక): agentic AI for timely justice

India has about **5.8 crore pending court cases** (NJDG, Oct 2026) and **4.34 lakh undertrial prisoners (75.8% of all prisoners)**,
many of whom Section 479 BNSS entitles to release. Most people who qualify for free legal aid never reach a lawyer.
NyayaVedika is a set of LangGraph agents that help the people and offices already working on this: legal-aid access,
case-file summarisation, undertrial release tracking, case triage and cause-list scheduling. A human approves every step with legal consequences.

**Track:** Timely Justice — Legal Backlog (Code for a Billion, impact area 07)

**Live demo:** DEMO_LINK_HERE (deployed on CLOUD_HERE) · **2–3 min video:** VIDEO_LINK_HERE · **Problem, sources and impact plan:** [SUBMISSION.md](SUBMISSION.md)

## Judging criteria, with evidence

| Criterion | Evidence | Where |
|---|---|---|
| Size of the problem | 5.83 crore pending cases; ~10 crore people waiting; 61.7 lakh cases over 10 years old; over 80% of citizens entitled to free legal aid | [SUBMISSION.md §1](SUBMISSION.md) |
| Severity | 75.8% of prisoners are undertrials; litigants' hearing time costs ~₹50,387 crore a year (0.48% of GDP) | [SUBMISSION.md §2](SUBMISSION.md) |
| Quality of the solution | Five agents, rules in code, grounded and verified outputs, PII masking, offline fallback, a test suite that needs no keys, 21 gold cases for the Sec. 479 engine | below, [docs/EVAL.md](docs/EVAL.md), [tests/](tests) |
| Proven impact | Event log and CSV export are built in. **Pilot results: pending** (see [docs/PILOT_GUIDE.md](docs/PILOT_GUIDE.md)). Simulation numbers are synthetic and labelled so. | [SUBMISSION.md §4](SUBMISSION.md) |

## Agents

```
                       ┌─────────────── Nyaya Mitra (ReAct + interrupt) ───────────────┐
 citizen / paralegal → │ agent ⇄ tools: legal-aid eligibility · Sec.479 calc · search_law │
                       │        (Pinecone) · web_search (Tavily, gov domains) · lookup_case│
                       └──────────────────────────────────────────────────────────────────┘
 case file → Document Analyst: ocr → index(Pinecone) → plan ─┬─────────────→ synthesize → verify ─┬→ persist → handoff
                                                             └→ map_part×N ↗        ↑    (fix ≤2x)┘   (re-score case,
                                                                (Send fan-out)      └──────────────     alert Undertrial Watch)
 nightly  → Undertrial Watch: scan custody cases → draft×N (Send) → save alerts → [lawyer approves] → apply
 weekly   → Registry Agent:  triage → AI review (±10, logged) → schedule → explain → [registrar approves] → publish
 staff    → Registry Copilot (ReAct): priority_cases · lookup_case · draft_document · search_law · web_search
```

Every legal rule (eligibility, thresholds, scores) is deterministic code with reasons. The LLM chooses tools, reads documents,
explains results and drafts documents. Human approval uses LangGraph `interrupt()`, and checkpoints live in Postgres, so a paused
case survives restarts. Every outcome is logged to `impact_events` for impact reporting.

**Section 479 release check** (`nyayavedika/triage.py::undertrial_release_check`) is plain code, never the LLM. It returns
`eligible`, `likely_eligible`, `needs_review` or `not_eligible`, and every status still goes to a lawyer.
It is pinned by `tests/gold_479.json` (hand-derived from the statute, **not yet lawyer-verified**).

## Results so far (synthetic data, not field results)

600-case synthetic docket, 5 benches, 5 working days ([docs/EVAL.md](docs/EVAL.md), [docs/SIMULATION.md](docs/SIMULATION.md)):
critical-case wait 0.09 days vs 1.40 for an oldest-first list; 0 advocate double-bookings vs 275; field extraction 69/70 on 10 sample files.

## Quick start (runs offline with no API keys)

```bash
pip install -r requirements.txt
cp .env.example .env          # then set three different long random DEMO_TOKEN_* values
python scripts/reset_demo.py  # seeds synthetic data
python server.py              # http://127.0.0.1:8000  (/staff for staff + lawyers, /citizen for citizens)
python -m unittest discover -s tests
```

Add `AZURE_OPENAI_*`, `PINECONE_API_KEY` and `TAVILY_API_KEY` to `.env` to switch on the LLM, vector search and web search.
No FastAPI on your machine? `python scripts/dev_api.py` serves the same pages on port 8010.
Full setup, Docker, background jobs, API table: [docs/SETUP.md](docs/SETUP.md). A 7-minute walkthrough: [docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md).

## Built with AgentFoundry

AF_SECTION_HERE

## Privacy and limits

- Email, Aadhaar, PAN, phone and card numbers are masked before text reaches the LLM, Pinecone or web search. **Names and addresses are not masked**, so do not upload real case files to a hosted model without consent.
- Web search is limited to official legal and government domains.
- The demo uses static bearer tokens per role. Set `DEMO_MODE=false` and use real authentication before any deployment with real data.
- The statutes table (46 rows) is demo data and rows without `verified_by` are marked UNVERIFIED.
- Outputs are legal information for a lawyer to review, not legal advice. Nothing is filed without a human decision.

Open source under the [MIT licence](LICENSE). Credits: [docs/CREDITS.md](docs/CREDITS.md).
