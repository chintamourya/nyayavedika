# NyayaVedika (న్యాయవేదిక): agentic AI for timely justice

**Track:** Timely Justice, Legal Backlog (Code for a Billion, impact area 07)
**Live demo:** DEMO_LINK_HERE · **Demo video (2–3 min):** VIDEO_LINK_HERE · **Licence:** MIT
**Detailed evidence and research:** [docs/RESEARCH_EVIDENCE.md](docs/RESEARCH_EVIDENCE.md)

Figures are tagged **Reported** (published by the named source), **Derived** (our arithmetic on reported figures) or **Estimate** (our model, assumptions stated).

---

## Problem statement

India's law already says when many undertrial prisoners must be released. Section 479 of the Bharatiya Nagarik Suraksha Sanhita (BNSS) requires release after half the maximum sentence, or one-third for first-time offenders. What is missing is someone, or something, that **notices the date, prepares the paperwork and puts the decision in front of a human on time**.

Three groups fall through the same gap:
- **People in custody and their families**, who cannot find or afford a lawyer and do not know they may be eligible for release or free legal aid.
- **Advocates**, who lose hours assembling, paginating and reading very long case papers before a hearing can be useful.
- **Courts and registries**, where triage, scheduling clashes and incomplete papers feed adjournments and a growing backlog.

## What you built

NyayaVedika is a set of AI agents and a lawyer workbench with three doors. Every legal rule (eligibility, Section 479 thresholds, urgency scores) is **deterministic code that shows its reasons**. The language model chooses tools, reads documents, explains and drafts. It never decides eligibility. **A human approves every step that has legal consequences.**

| Door | Feature | What it does | What it eases | How impact is measured |
|---|---|---|---|---|
| **Citizen** `/citizen` (no login; English, Hindi, Telugu) | Free legal aid check | 5 questions, then an AI explanation and a drafted application | The legal-aid reach gap (about 0.15% of those entitled) | Checks, eligible, applications, partner-reported outcomes |
| | Understand a legal problem | Searches statutes and official government sites; asks for missing facts | Not knowing which law or office applies | Citizen sessions |
| | Understand a court document | Plain-language brief of an order or notice | Being unable to read what the court sent | Documents analysed |
| | Know your rights | Rights guidance, including for someone in custody | Families who do not know what to ask for | Citizen sessions |
| **Advocate** `/advocate` (lawyer token) | Document Studio | Merge, split into volumes, reorder, rotate, remove pages, OCR, bookmarks, clickable index, page numbers, all in memory | Hand-assembling paper-books in several desktop tools | Pages and operations per session |
| | AI Document Insights | Issues, Facts, Background or Summary of a PDF, DOCX, text or image (up to 50 pages). Every point has a page number and a verbatim excerpt checked against the text | Hours of reading; unverifiable AI claims | Documents analysed, upload-to-result time |
| | Chat with this document | Page-cited answers from the lawyer's own document only | Hunting through a file for one fact | Questions per session |
| **Court staff** `/staff` | Intake and Docket | Reads case files and scores every pending case, with reasons | Manual sorting of the docket | Cases triaged |
| | Cause list | Conflict-free weekly hearing list sized by adjournment risk; registrar approves | Clashes and adjourned hearings | Cases listed, conflicts avoided, critical wait gained |
| | **Undertrial Watch** (nightly) | Computes the Section 479 threshold, itemises the arithmetic, drafts the release application; lawyer approves | Eligible people missed because nobody checked the date | People flagged, applications approved, custody days over the limit |
| | Document summary, ADR routing, Insights tab | Briefs any document; routes suitable cases to Lok Adalat; weekly docket health | Reading time; cases that need not go to trial | Documents analysed, ADR candidates |
| **All** | Feedback wall `/feedback` | Public ratings and notes from field users | No evidence of real-world use | Responses, average rating, share whose situation changed |

```mermaid
flowchart LR
    C["Citizen /citizen"] --> NM["Nyaya Mitra agent"]
    A["Advocate /advocate"] --> DA["Document Analyst"]
    A --> WB["Studio + Document Chat"]
    S["Staff /staff"] --> RA["Registry agents"]
    S --> UW["Undertrial Watch"]
    NM & DA & RA & UW --> RULES["Deterministic rules in code<br/>Sec. 479, legal aid, triage"]
    NM & DA & WB --> PII["PII masking"] --> LLM["Azure OpenAI<br/>offline fallback"]
    NM & DA & WB --> KB["Pinecone + gov-domain web search"]
    UW --> G1{{"Lawyer approves"}}
    RA --> G2{{"Registrar approves"}}
    Agents["All agents"] --> IMP["Impact log + feedback wall"]
```

**Why the design works**
- **Rules in code, not model output.** `nyayavedika/triage.py` returns `eligible`, `likely_eligible`, `needs_review` or `not_eligible`, and every status goes to a lawyer. For a three-year maximum offence, a first-time offender is eligible after one year and others after eighteen months.
- **It targets the measured gap.** NALSA's own report shows the weak points are identification, filing in some states, pending applications and surety-blocked release. Undertrial Watch lists, itemises and drafts for exactly these.
- **Human approval at every consequential step**, using LangGraph `interrupt()` with Postgres checkpoints, so a paused case survives a restart.
- **Grounded outputs.** Briefs are verified against the source. Insights need a page and a checked excerpt. Chat cites a page for every statement.
- **Privacy.** Phone, email, Aadhaar and PAN numbers are masked before text reaches any model, index or web search. Web search is limited to official domains. Advocate workspaces use random tokens stored only as SHA-256 hashes.
- **Works without keys.** With no API key the app runs offline on rules.

**How we used AgentFoundry (AF):** AF_SECTION_HERE

## Scale & severity of the problem

### Scale

| Population | Figure | Source and date | Type |
|---|---|---|---|
| People waiting on a court | **5.64 crore pending cases** (district 4.98 crore, High Courts about 64 lakh, Supreme Court about 96,000) | Law Ministry, Rajya Sabha, 23 July 2026 | Reported |
| People in jail without a conviction | **4,03,302 of 5,31,949 prisoners (75.81%)**, October 2025 | NALSA, UTRC report Oct–Dec 2025 | Reported |
| People entitled to free legal aid | **About 80% of the population**, over 110 crore people | India Justice Report 2025; our arithmetic | Reported / Derived |

Every case has at least two parties, plus families and witnesses, so the people affected exceed the case count. One person can be in several cases, so we claim no exact number of people.

### Severity

- **Long detention without conviction.** Of 3,89,910 undertrials at the end of 2023, **1,19,654 had been held over a year, 64,999 over two years and 10,392 over five** (NCRB). Prisons were at **120.8% occupancy** (Reported).
- **The remedy is not reaching enough people.** In Oct–Dec 2025 the review committees **identified 14,387 prisoners, recommended 10,754, saw 9,011 applications filed and 5,864 released**. Only 2.7% of prisoners were identified (NALSA, Reported). Release rates differ by state: Maharashtra 17%, Telangana 25%, Andhra Pradesh 53% of those recommended (Derived).
- **Few people reach a lawyer.** Free legal aid reached 16,60,249 people in FY 2025-26 up to January 2026, about **0.15%** of those entitled (Derived).
- **Economic loss.** Litigants lose **₹50,387 crore a year** in wages and business income (0.48% of GDP; DAKSH, 2015–16, Reported). The state spends about **₹4,195 per inmate per month** (NCRB ₹2,669.88 crore in FY 2023–24; Derived).
- **Our estimate of avoidable custody** (Estimate): between **11,021 and 71,792 people** eligible but still held, about **₹13.9 crore to ₹361.4 crore** in direct custody cost, with ₹74.4 crore as the central case. Method and assumptions are in the evidence file.

### How the harm ripples

| Stage | What happens | Where NyayaVedika cuts the chain |
|---|---|---|
| 1. Trigger | A person crosses the half or one-third threshold and nobody checks the date | Nightly automated threshold check |
| 2. Direct harm | Continued custody without conviction; only 55% of those recommended were released | A ready, reasoned application and a named reviewer |
| 3. Spread | The household loses its earner, borrows for lawyers and travel, children may leave school; the state keeps paying | Earlier release and earlier counsel |
| 4. System feedback | Overcrowding, more adjournments, a larger backlog | Cleaner listing and complete case papers |

The cycle reinforces itself. The people not identified are the least able to find a lawyer (only 7.91% of undertrials used free legal aid in 2016–19), and each missed release adds to the overcrowding that makes the next review harder. The largest costs, to households and public trust, are also the least measured, so **we put no number on the ripples** beyond the custody floor above. Full evidence tables are in [docs/RESEARCH_EVIDENCE.md](docs/RESEARCH_EVIDENCE.md).

## Proven impact

**Honest status:** no real field deployment yet. What exists today:
- **Synthetic checks.** 21 hand-derived Section 479 cases (`tests/gold_479.json`, **not yet verified by a lawyer**) and an offline evaluation (`python scripts/eval_demo.py`). These use invented cases, so they show the system behaves as designed, not how a real court performs.
- **Built-in measurement.** Every feature writes counts-only events to `/api/impact` (CSV export), and `scripts/pilot_report.py` turns a per-case pilot log into the table below.
- **Pilot and field feedback.** Testers use the live demo and the feedback wall, and lawyers time one task with and without the tool. The protocol is in the evidence file.



## Run it

```bash
pip install -r requirements.txt     # Python 3.12
cp .env.example .env                # set distinct long random DEMO_TOKEN_* values
python scripts/reset_demo.py        # seeds synthetic data
python server.py                    # http://127.0.0.1:8000
python -m unittest discover -s tests
```

Open `/citizen`, `/advocate` or `/staff`. Add `AZURE_OPENAI_*`, `PINECONE_API_KEY` and `TAVILY_API_KEY` to `.env` to switch on the LLM, vector search (needed for document chat) and web search. Scanned pages need Tesseract with language packs (`apt install tesseract-ocr tesseract-ocr-hin tesseract-ocr-tel`). `docker compose up --build` runs the full stack.

## Known limits

- Triage points, income limits and the statutes table (46 rows of demo data) need lawyer review. The demo uses static role tokens, not real authentication. Set `DEMO_MODE=false` and use real authentication before any deployment with real data.
- The release check sees only docket fields, so a lawyer confirms before filing. Records are fragmented, so we use bulk imports and OCR of remand sheets, not a live e-Prisons link.
- Names and addresses are not masked. Do not upload real case files to a hosted model without consent.
- Document chat needs Pinecone and the language model. Studio takes PDFs only, and Insights are capped at 50 pages.
- Poverty can still block release when a court has ordered it, for example when no surety can be found.
- Outputs are legal information for a lawyer to review, not legal advice. Nothing is filed without a human decision.

## Licence

Open source under the [MIT licence](LICENSE). Built for the Code for a Billion hackathon by Code for India.