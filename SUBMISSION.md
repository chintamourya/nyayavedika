# NyayaVedika (న్యాయవేదిక): Code for a Billion submission

**Theme:** Timely Justice / Legal Backlog. It covers case triage, document summarisation, legal aid access and court scheduling efficiency.

**Repo:** this repository · **Demo:** link at the top of [README.md](README.md)

> Every figure below carries a source link. Court-pendency figures come from the National Judicial Data Grid (NJDG),
> either read from the live dashboard on 23 Oct 2026 or quoted from the Law Minister's replies to Parliament, which cite NJDG.
> Items we estimated ourselves are labelled **estimate**. Simulation results are labelled **synthetic**.

---

## Judging at a glance

Each criterion is worth 25 points. Judges score independently and the scores are averaged. Ties go to proven impact, then size of the problem.

| Criterion | Headline evidence | Where | Status |
|---|---|---|---|
| **Size of the problem** | 5.83 crore pending cases (NJDG, Oct 2026), on the order of 10 crore people waiting; 61.7 lakh cases over 10 years old | §1 | Sourced from NJDG and Parliament replies |
| **Severity** | 4,34,302 undertrials (75.8% of prisoners) while Sec. 479 BNSS entitles many to release; litigants' hearing time costs about ₹50,387 crore a year (0.48% of GDP) | §2 | Sourced from NCRB, DAKSH and Supreme Court orders |
| **Quality of the solution** | Five LangGraph agents with human approval at every legal step; rules in code, grounded outputs, PII masking; a unit-test suite that runs offline, including 21 gold cases for the Sec. 479 rule engine; reproducible simulation | §3 | Built and tested; simulation is synthetic |
| **Proven impact** | Event log and CSV export built in; pilot plan with baselines and named data sources | §4 | **Pilot results pending** |

---

## 1. Size of the problem (25)

| Indicator | Figure | Source |
|---|---|---|
| Cases pending in District & Taluka courts | **5,17,65,573** (4.05 crore criminal, 1.12 crore civil) | NJDG district dashboard, last updated 23-10-2026 |
| Cases pending in High Courts | **65,48,587** | NJDG High Court dashboard, read Oct 2026 |
| Cases pending in all courts (cross-check) | **5.64 crore** incl. Supreme Court (~96,000) and 25 High Courts | Law Minister, written reply to Rajya Sabha, July 2026, citing NJDG ([Telangana Today](https://telanganatoday.com/more-than-5-64-crore-cases-pending-across-indian-courts-rs)) |
| Backlog at end-2025 (for trend) | District 4,76,57,328; High Courts 63,66,023; Supreme Court 92,101 (as of 31 Dec 2025) | Law Minister, Lok Sabha, 13 Feb 2026, citing NJDG ([IANS](https://ianslive.in/over-476-crore-cases-pending-across-indian-courts-govt-tells-parliament--20260213184542)) |
| District court cases pending **over 10 years** | **47,00,248** (9%) | NJDG, 23-10-2026 |
| High Court cases pending **over 10 years** | **14,74,381** (23%) | NJDG, Oct 2026 |
| High Court cases pending **over 30 years** | **80,660** | Rajya Sabha reply, July 2026, citing NJDG ([NewsBytes](https://www.newsbytesapp.com/news/india/decades-long-case-backlog-in-indian-courts/story)) |
| Undertrial prisoners | **4,34,302, or 75.8%** of 5,73,220 prisoners (31 Dec 2022) | NCRB *Prison Statistics India 2022* ([LiveLaw](https://livelaw.in/news-updates/ncrb-releases-prison-statistics-india-report-2022-243973)). The India Justice Report 2025 also puts undertrials at 76% and prison occupancy at 131% ([summary](https://www.drishtiias.com/daily-updates/daily-news-analysis/india-justice-report-2025/print_manually)) |
| Citizens entitled to free legal aid | **Over 80% of the population** (all women and children, SC/ST, persons with disability, people in custody, industrial workers, and everyone under the State income limit; Sec. 12, Legal Services Authorities Act 1987) | India Justice Report 2019, quoted in [LiveLaw](https://www.livelaw.in/amp/columns/legal-aid-services-constitution-of-india-legal-services-authorities-act-nalsa-214034) |

**Reach (estimate):** about 5.8 crore pending cases. Every case has at least two parties, plus families and witnesses, so
**on the order of 10 crore people** are waiting on a court today. Some people are parties to several cases, so we
treat 10 crore as a round figure and not a count.

## 2. Severity (25)

- **Liberty lost.** Under Sec. 479 BNSS (earlier Sec. 436A CrPC), an undertrial who has served **half** the maximum sentence
  (**one-third** for a first-time offender) must be released on bond. The benefit does not apply to offences punishable with
  death or life imprisonment, and not where the person has more than one case pending (Sec. 479(2)).
  The jail superintendent must apply to the court once the threshold is reached (Sec. 479(3)).
  The Supreme Court held in August 2024 that it covers all undertrials in pending cases, including cases registered before
  BNSS came into force on 1 July 2024 ([MHA advisory, Oct 2024](https://sabrangindia.in/under-trial-prisoners-mha-directs-states-uts-to-implement-section-479-of-bnss);
  [Supreme Court order of 19 Nov 2024](https://www.verdictum.in/court-updates/supreme-court/in-re-inhuman-conditions-in-1382-prisons-release-undertrial-prisoners-prolonged-incarceration-1559091);
  [analysis of the provision](https://www.barandbench.com/columns/analysing-the-remedy-of-bail-under-section-479-of-bnss)).
  The Court has had to keep pressing for compliance. In November 2024 it recorded that Uttar Pradesh, Bihar, Tripura and Goa had not
  responded on implementation. It also directed legal services authorities to mobilise panel lawyers and paralegal volunteers to keep the
  list of eligible undertrials up to date, as a continuing process led by the District Undertrial Review Committees.
- **Decade-long waits.** About **61.7 lakh** cases (district + High Court) are over 10 years old, and 80,660 High Court cases are over 30 years old.
  Many involve maintenance, wages, accident compensation or land, where the delay itself causes the harm.
- **Economic loss.** DAKSH's *Access to Justice Survey* (2016; 9,329 litigants, 184 districts, 24 states) estimated that
  litigants' time spent attending hearings costs about **₹50,387 crore a year, roughly 0.48% of GDP**. An average litigant spent
  **₹520** and lost about **₹873** in wages for each day in court, and litigants earning under ₹1 lakh a year spent about a quarter of
  their income on attending hearings, before legal fees ([DAKSH](https://www.dakshindia.org/access-to-justice-survey-findings-india)).
  DAKSH's *Paths to Justice* survey (50,000 households, 2017) found court proceedings cost about ₹1,049 a day, nearly twice the
  ₹659 for out-of-court routes ([Bar & Bench](https://www.barandbench.com/columns/justice-daksh-survey-2017)).
- **Adjournments eat court time.** In a time-and-motion study of four Bengaluru courts, adjournments and summons took about **54%** of sitting
  time in civil courts and **33%** in criminal courts ([DAKSH, 2016](https://dakshindia.org/wp-content/uploads/2016/11/DAKSH-TIME-AND-MOTION-STUDY-OF-FOUR-DISTRICT-AND-SESSIONS-COURTS.pdf)).
  It is a small, older, single-city study, so we use it as an indication, not a national rate.
- **Legal aid that people don't reach.** About **15 million** people have received legal aid since 1995 (India Justice Report 2019). That is
  roughly 6 lakh a year on average (our arithmetic: 15 million over 24 years), against the 80%+ of the population who are entitled.
  A 2018 CHRI study found it took on average **11 days** to get a lawyer after applying, against NALSA's 7-day norm for deciding an application.
  The India Justice Report 2025 reports legal-aid spending of about ₹6 per person and a 38% fall in paralegal volunteers over five years
  (secondary summaries: [LiveLaw](https://www.livelaw.in/amp/columns/legal-aid-services-constitution-of-india-legal-services-authorities-act-nalsa-214034),
  [IJR 2025](https://www.drishtiias.com/daily-updates/daily-news-analysis/india-justice-report-2025/print_manually)).
- **Capacity is part of the cause.** One study of district courts found that each additional judge filled into a vacant post raised the court's
  disposal rate by about 6% ([Rao 2019, via Ideas for India](https://www.ideasforindia.in/topics/governance/how-district-courts-influence-firm-growth.html)).
  NyayaVedika does not create judges. It helps the courts, jails and legal-aid offices that exist spend their time on the cases that cannot wait.

## 3. Quality of the solution (25)

NyayaVedika is an **agentic system built on LangGraph**, not a form-based web app. Five agents divide the work.
Each one plans and acts for itself, but humans approve every step with legal consequences.

| Agent | Who it serves | What it decides on its own | Human checkpoint |
|---|---|---|---|
| **Nyaya Mitra** (ReAct) | Citizens, paralegals, jail-visiting lawyers. Works in Indian languages. | Which tools to call: legal-aid eligibility, Sec. 479 computation, statute search (Pinecone), official-site search (Tavily), case lookup. It asks clarifying questions when facts are missing. | Pauses for the person's answers (LangGraph `interrupt`) |
| **Document Analyst** | Registry, judges, legal-aid lawyers | OCRs only the scanned pages. Chooses single-pass or parallel map-reduce. **Verifies its own brief against the source and rewrites when a claim isn't grounded (up to two repair rounds).** Re-prioritises the linked case and alerts Undertrial Watch. | Verification report shown with every brief |
| **Undertrial Watch** (runs nightly) | DLSAs, Undertrial Review Committees | Scans every custody case, computes release eligibility and drafts the Sec. 479 application | **A lawyer approves before anything is filed**, and checks for other pending cases (Sec. 479(2)) |
| **Registry Agent** | Court registry | Triages the whole docket. AI-reviews edge cases (adjustments capped at ±10, each logged). Builds a conflict-free cause list sized by adjournment risk, and explains it. | **The Registrar approves before publishing** |
| **Registry Copilot** (ReAct) | Court staff | Answers docket questions and drafts routine documents | Only gives recommendations |

**What each agent changes, and how we will see it:**

| Harm | What the code does | Who gains | How it is measured |
|---|---|---|---|
| People held past the Sec. 479 threshold | Nightly custody scan, release arithmetic, ready-to-file draft | Eligible undertrials, DLSAs, review committees | Flagged → approved → released (partner register) |
| Entitled people never get a lawyer | Eligibility check, clause, forum, documents and application draft in the person's language | Citizens, paralegals, jail-visiting lawyers | Eligible found, applications, days to lawyer |
| Staff spend hours understanding files | Verified brief with every date and statute checked against the source | Registry, judges, legal-aid lawyers | Timed sample; lawyer-checked accuracy |
| Hearings lost to adjournments and clashes | Urgency-ranked, conflict-free cause list sized by adjournment risk | Registry, advocates, litigants | Adjourned hearings in listed matters (registry data) |

**How it fits the law as it stands.** Sec. 479 already puts the duty to apply on the jail superintendent, and the Supreme Court has made
District Undertrial Review Committees responsible for identifying eligible people. Undertrial Watch does not replace them. It gives them a
nightly, itemised list with the arithmetic shown and a ready draft, so a missed date becomes a visible alert.

**Design choices that matter in court:**
- **Legal rules stay in code; the LLM makes judgement calls.** Eligibility, thresholds and scores are
  deterministic and auditable, and every score comes with its reasons. The LLM chooses which tools to use,
  explains results and drafts documents. The Sec. 479 calculation is unit-tested, including the one-third rule for
  first-time offenders and the exclusion of life-sentence offences.
- **Grounded outputs.** Every date and statute in a brief must literally appear in the source, and an LLM
  verifier checks each claim against excerpts (adapted from the validators in our case-search codebase).
- **Privacy.** Phone, email, Aadhaar and PAN numbers are masked before text reaches the LLM. The impact log and
  legal-aid tables store categories and districts, never identities.
- **Open and low-cost.** Tesseract OCR (Indic language packs), Postgres, and free tiers of Pinecone and Tavily.
  If the LLM is down, the system falls back to offline rules.
- **Known limits.** The release check flags *apparent* eligibility from the docket fields. It reports `needs_review` when several sections or other pending cases are recorded, but it cannot see cases that are not in the docket,
  so a lawyer confirms that before filing. Income limits for legal aid differ by State and are set per pilot State in configuration.

**Simulated effectiveness (synthetic data, not field results).** 600-case synthetic docket, 5 benches, 5 working days, seed 42.
Pinned by `python -m unittest tests.test_data_model` (stateless planner). The last column repeats the run over seeds 1–10.
The memory-aware planner (Phase 5) lists all 600 cases at about 66% bench utilisation, against 501 and 54% before, with 0 invariant violations.
The 8-week rolling simulation is in `docs/SIMULATION.md` (`python scripts/simulate_8_weeks.py`). With aging, 0 cases are past their deadline; without it, 154 (synthetic data).

| Metric | NyayaVedika | Oldest-first list | Seeds 1–10 (NyayaVedika vs oldest-first) |
|---|---|---|---|
| Average wait for a critical case (working-day index; 0 = first day listed) | **0.09** | 1.40 | 0.00–0.22 vs 0.95–1.24 |
| Advocate double-bookings | **0** | 275 | 0 vs 227–283 |
| Expected effective hearings | **228** | 203 (+12%) | +8.9% to +28.9%, mean +18% |

*Updated for triage rules-v2:* statutory-timeline matters (Sec. 138 NI Act, maintenance, domestic violence) now get +3 points.
Before that change the same run gave 0.11 days and 229 hearings (rules-v1). The test suite pins these numbers.

"Expected effective hearings" adds up (1 − adjournment risk) over the listed cases, using the system's own risk model, so it is a modelled figure.
The unit tests (`python -m unittest discover -s tests`, 124 at the end of Phase 5) also check the scheduling invariants on every plan: no advocate double-booked, no bench over capacity, nothing lost, and critical cases listed by their deadline or alerted.

## 4. Proven impact (25): deployment plan and measurement

**Status:** pilot results are pending. How the pilot is run and measured: `docs/PILOT_GUIDE.md`; the results table is generated by `python scripts/pilot_report.py`. The table below shows what will be reported and where each number comes from.

Every agent writes outcome events to Postgres (`impact_events`). **Impact** tab → **Export CSV** gives the raw evidence log.
Events hold counts and categories only, never identities. A person visiting through chat or through the eligibility form counts as one
session. Undertrial alerts are created once per case while pending or approved, so "flagged" counts cases and not nightly repeats.
Outcomes after a referral (lawyer assigned, release granted) are reported by the partner through `/api/legal-aid/{id}/outcome` and the
partner's own register. The system does not observe them on its own.

**Pilot (4–6 weeks)** with one partner. In order of preference:
1. A **District Legal Services Authority** front office or jail legal-aid clinic, using Nyaya Mitra, Legal Aid Check and Undertrial Watch.
2. A **law-school legal aid clinic** or NGO doing jail visits, using the same tools.
3. A **district court registry**, running the Registry Agent in shadow mode next to the existing cause list.

| Measure | Baseline (before) | Pilot result (after) | Source |
|---|---|---|---|
| People assisted (sessions; no identities are stored, so this is not a unique-person count) | n/a | `people_reached` | impact log |
| People found eligible for free legal aid | | `legal_aid.found_eligible` | impact log |
| Days from application to lawyer assigned | 11 days on average nationally (CHRI 2018, as quoted in [LiveLaw](https://www.livelaw.in/amp/columns/legal-aid-services-constitution-of-india-legal-services-authorities-act-nalsa-214034)); replace with the partner's own register | | partner register + `legal_aid_outcome` events |
| Applications filed / lawyers assigned | partner's register | `legal_aid_outcome` events | partner + log |
| Undertrials flagged → applications approved → released | partner's register | `undertrials.*` + partner follow-up | partner + log |
| Minutes to understand a case file | timed sample (n≥20) | timed sample (n≥20) | stopwatch study |
| Brief accuracy (claims verified by a lawyer) | n/a | % correct, n≥30 documents | expert review |
| Adjourned hearings in listed matters | registry data | registry data | court registry |
| User rating | n/a | `feedback.avg_rating` | in-app |

**Add real pilot numbers before submitting.** Judges weight real deployment data most heavily, and it is the first tie-breaker.

## Sources

- NCRB *Prison Statistics India 2022*: [LiveLaw](https://livelaw.in/news-updates/ncrb-releases-prison-statistics-india-report-2022-243973)
- Court pendency (Parliament replies citing NJDG): [IANS, Feb 2026](https://ianslive.in/over-476-crore-cases-pending-across-indian-courts-govt-tells-parliament--20260213184542); [Telangana Today, Jul 2026](https://telanganatoday.com/more-than-5-64-crore-cases-pending-across-indian-courts-rs); [NewsBytes, Aug 2026](https://www.newsbytesapp.com/news/india/decades-long-case-backlog-in-indian-courts/story)
- Sec. 479 BNSS: [Bar & Bench](https://www.barandbench.com/columns/analysing-the-remedy-of-bail-under-section-479-of-bnss); [Supreme Court order, 19 Nov 2024 (Verdictum)](https://www.verdictum.in/court-updates/supreme-court/in-re-inhuman-conditions-in-1382-prisons-release-undertrial-prisoners-prolonged-incarceration-1559091); [MHA advisory (Sabrang)](https://sabrangindia.in/under-trial-prisoners-mha-directs-states-uts-to-implement-section-479-of-bnss)
- Legal aid: [LiveLaw column on legal-aid statistics](https://www.livelaw.in/amp/columns/legal-aid-services-constitution-of-india-legal-services-authorities-act-nalsa-214034); [India Justice Report 2025 summary](https://www.drishtiias.com/daily-updates/daily-news-analysis/india-justice-report-2025/print_manually)
- DAKSH: [Access to Justice Survey](https://www.dakshindia.org/access-to-justice-survey-findings-india); [Paths to Justice (Bar & Bench)](https://www.barandbench.com/columns/justice-daksh-survey-2017); [Time and motion study](https://dakshindia.org/wp-content/uploads/2016/11/DAKSH-TIME-AND-MOTION-STUDY-OF-FOUR-DISTRICT-AND-SESSIONS-COURTS.pdf)
- Courts and firm growth: [Rao (2019), via Ideas for India](https://www.ideasforindia.in/topics/governance/how-district-courts-influence-firm-growth.html)