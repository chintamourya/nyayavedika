# NyayaVedika: research and evidence file

Real users feedback link : https://nyayavedika.delightfulmushroom-95327f3a.koreacentral.azurecontainerapps.io/feedback

This file holds the full evidence behind the README's claims about size, severity and impact. It is written for judges and partners who want to check the numbers. The README carries the short version.

**How figures are tagged.** **Reported**: published by the named source. **Derived**: our arithmetic on reported figures, shown so it can be checked. **Estimate**: our model, with assumptions stated and changeable.

**Status of impact evidence.** There is no real field deployment yet. Section 7 says what exists today, Section 8 gives the protocol for collecting real evidence, and nothing in this file is presented as field impact.

Contents: 1 Scale · 2 Severity · 3 Economic loss · 4 Avoidable custody model · 5 How the harm ripples · 6 From evidence gap to feature to indicator · 7 What is proven today · 8 Measurement protocol · 9 Limits of this evidence · 10 Sources

---

## 1. Scale

| Population | Figure | Source and date | Type |
|---|---|---|---|
| Pending cases, all courts | **5.64 crore**: district and subordinate 4.98 crore, High Courts about 64 lakh, Supreme Court about 96,000 | Law Ministry, Rajya Sabha, 23 July 2026 (NJDG as of 16 July 2026) | Reported |
| Pending cases six months earlier | 5.39 crore at 31 December 2025 | Law Ministry, Lok Sabha, 13 February 2026 | Reported |
| Cases pending over 30 years | 81,275 in district courts, about 80,600 in High Courts | Rajya Sabha reply, July 2026 | Reported |
| Prisoners | 5,31,949, of whom **4,03,302 (75.81%) are undertrials**, October 2025 | NALSA, UTRC report Oct–Dec 2025 | Reported |
| Entitled to free legal aid | **About 80% of the population**, over 110 crore people | India Justice Report 2025 (share); population of about 1.4 billion is our assumption | Reported / Derived |

**Reading the numbers.** Every pending case has at least two parties, and families and witnesses are affected too, so the people touched by delay exceed the case count. One person can be in several cases, so no exact number of people is claimed. "Entitled" means eligible by law, not in need in a given year. Pendency rose by about 25 lakh cases in six months (5.39 to 5.64 crore, Derived), which is the live trend the tool is meant to bend. The [NJDG](https://njdg.ecourts.gov.in/) dashboard is the reference for today's count.

## 2. Severity

### 2.1 Length of detention without conviction

| Measure | Figure | Source | Type |
|---|---|---|---|
| Undertrials at end of 2023 | 3,89,910 | NCRB, Prison Statistics India (PSI) 2023 | Reported |
| Held over 1 year | **1,19,654** | PSI 2023 | Reported |
| Held over 2 years | **64,999** | PSI 2023 | Reported |
| Held over 3 years | **33,398** | PSI 2023 | Reported |
| Held over 5 years | **10,392** | PSI 2023 | Reported |
| Held over 3 years at end of 2024 | Nearly 30,000 (8.1%) | PSI 2024 | Reported |

### 2.2 Overcrowding

5,30,333 prisoners in space for 4,39,119 gives **120.8% occupancy** at the end of 2023 (PSI 2023). It was 112.7% at the end of 2024 (PSI 2024).

### 2.3 The legal remedy exists, and the funnel leaks

Section 479 BNSS requires release after half the maximum sentence, or one-third for first-time offenders. The review committees (UTRCs) report the following for October to December 2025 (NALSA, Reported). Rates in the last column are Derived.

| Category | Identified | Recommended | Applications filed | Released | Released ÷ recommended |
|---|---|---|---|---|---|
| Section 479, half sentence | 209 | 175 | 164 | 96 | 55% |
| Section 479, first-time offender, one-third | 279 | 255 | 250 | 209 | 82% |
| Bail granted but surety not furnished | 4,345 | 3,455 | 3,085 | 1,936 | 56% |
| Women undertrials | 2,885 | 1,416 | 1,234 | 514 | 36% |
| **All 16 categories** | **14,387** | **10,754** | **9,011** | **5,864** | **55%** |

**Stage-by-stage conversion across all categories (Derived):**

| Step | Rate | What it tells us |
|---|---|---|
| Prisoners identified ÷ all prisoners | 2.7% (14,387 of 5,31,949) | Identification is the first bottleneck |
| Recommended ÷ identified | 75% | One in four identified people is screened out |
| Filed ÷ recommended | 84% | Filing is a smaller leak, but some states lag |
| Released ÷ filed | 65% | 1,946 applications were still pending and 834 had bail refused |
| Released ÷ identified | 41% | Four in ten identified people leave custody |

**State differences (Derived from NALSA state tables):** Maharashtra recommended 1,470 and released 255 (17%). Telangana recommended 554, filed 314 and released 140 (25%). Andhra Pradesh recommended 184 and released 98 (53%).

**Identification gap.** Only **488 people** were identified under the two Section 479 categories nationally in one quarter (209 + 279), while 64,999 undertrials had been held over two years at the end of 2023. The two figures come from different dates and not every long-held person is eligible, so the gap cannot be stated exactly. It is the reason identification is the first target of Undertrial Watch.

### 2.4 Access to a lawyer

| Measure | Figure | Source | Type |
|---|---|---|---|
| People reached by free legal aid and advice, FY 2025-26 up to January 2026 | 16,60,249 | Law Ministry, Lok Sabha, 13 March 2026 | Reported |
| Share of those entitled | About **0.15%** (16,60,249 ÷ 110 crore) | Our arithmetic | Derived |
| Public spending on legal aid | About ₹6.46 per person a year | India Justice Report 2025 | Reported |
| Undertrials who used free legal aid, 2016–19 | 7.91% | Surendranath and Andrew 2022 (NCRB admission data) | Reported |
| Lawyer type for the 10,754 recommended | 5,963 private, 4,730 legal aid, 16 none | NALSA | Reported |
| LADC scheme, FY 2025-26 to December 2025 | 2,76,476 represented, 59,630 released | Law Ministry | Reported |

Once a case is recommended, representation is almost universal (only 16 had no lawyer). The weak points sit **before** that step (identification) and **after** it (pending applications, surety, release). The LADC counts use different definitions from the committee data, so the two are not added together.

### 2.5 Who is most exposed

- **Women.** 1,049 women undertrials at the end of 2023 (NCRB). The Supreme Court directed on 19 November 2024 that eligible women prisoners be identified. In Q4 2025, 514 of 1,416 recommended women were released, 36% against 55% overall (Derived).
- **People with little education.** A quarter of prisoners are uneducated and over 40% are below Class X (PSI 2023). Whether low literacy changes bail outcomes is not measured.
- **People who cannot pay surety.** 4,345 were identified in Q4 2025 because bail was granted but surety was not furnished. A cash-bail scheme had a ₹20 crore outlay, with ₹28.67 lakh used and 144 prisoners helped (reported in press coverage).

## 3. Economic loss

| Loss | Figure | Source and date | Type |
|---|---|---|---|
| Litigants' lost wages and business income from attending hearings | **₹50,387 crore a year (0.48% of GDP)** | DAKSH Access to Justice Survey, 9,329 litigants, 2015–16 | Reported |
| Litigants' cost of attending hearings | About ₹30,000 crore a year | Same survey | Reported |
| Direct spend on prison inmates | **₹2,669.88 crore in FY 2023–24** | NCRB, expenses on inmates | Reported |
| Per inmate per month | **About ₹4,195** (₹2,669.88 crore ÷ 5,30,333 ÷ 12) | Our division | Derived |
| Total prison expenditure | ₹8,834.6 crore actually spent in FY 2023–24 | PSI 2023 | Reported |
| Court time lost | Adjournments and summons took about 54% of civil and 33% of criminal sitting time in a four-court study | DAKSH 2016 | Reported |

The DAKSH survey is ten years old, so today's loss is likely higher. It has **not** been scaled up. Avoidable custody is a small part of the ₹50,387 crore litigant loss, so the claim is a targeted contribution to one part of that loss, not a fix for all of it.

## 4. Avoidable custody: our model

**Question.** How many people could be eligible for release under Section 479 but are still in custody, and what does that cost?

**Method.**

```
Eligible people = pool × (1 − share with death or life offences) × (1 − share with other pending cases)
Person-months   = eligible people × months of delay
Custody cost    = person-months × ₹4,195
Custody days    = person-months × 30
```

The pool is the number of undertrials held longer than a chosen period (PSI 2023). The 1,19,654 held over a year is the upper bound on who could be eligible.

**Assumptions register (all are ours, not published figures):**

| Assumption | Conservative | Central | Progressive | Why this range |
|---|---|---|---|---|
| Pool | 33,398 (over 3 years) | 64,999 (over 2 years) | 1,19,654 (over 1 year) | Longer detention is more likely to pass a threshold |
| Excluded: offences punishable by death or life | 45% | 35% | 25% | Section 479 does not apply to them. No published share found |
| Excluded: people with other pending cases | 40% | 30% | 20% | Release is blocked if other cases are pending. No published share found |
| Delay between eligibility and release | 3 months | 6 months | 12 months | No published figure found |
| Cost per person-month | ₹4,195 | ₹4,195 | ₹4,195 | NCRB spend ÷ prisoners (Derived) |

**Results (Estimate):**

| Scenario | Eligible people | Delay | Person-months | Custody days | Direct custody cost |
|---|---|---|---|---|---|
| Conservative | 11,021 | 3 months | 33,063 | about 9.9 lakh | ₹13.9 crore |
| Central | 29,575 | 6 months | 1,77,450 | about 53 lakh | ₹74.4 crore |
| Progressive | 71,792 | 12 months | 8,61,504 | about 2.58 crore | ₹361.4 crore |

**What the cost covers.** Only average direct inmate spend. It leaves out lost wages, lost jobs, family costs and court time, so it is a floor.

**Illustrative sensitivity (not a forecast).** If a tool like this reached a given share of the central-case eligible people, and the release rate matched the national committee rate of 55%, the numbers would be:

| Share of eligible people reached | People released earlier | Custody days avoided (6-month delay) |
|---|---|---|
| 5% | about 800 | about 1.45 lakh |
| 10% | about 1,600 | about 2.9 lakh |
| 25% | about 4,000 | about 7.3 lakh |

The reach shares are arbitrary examples chosen to show scale, not predictions. A pilot with real custody records replaces every assumption in this section.

## 5. How the harm ripples

A missed release does not stay with one person. The cost travels in four stages, and each stage is a point where the chain can be cut.

| Stage | What happens | Evidence | Where it can be cut |
|---|---|---|---|
| 1. Trigger | A person crosses the half or one-third threshold and nobody checks the date. Identification relies on manual ledger audits and quarterly committee sittings | 209 identified under the half-sentence category in one quarter (NALSA) | Automated nightly threshold check |
| 2. Direct harm | Continued custody without conviction | 14,387 identified, 5,864 released, 55% of those recommended (NALSA) | A ready, reasoned application and a named reviewer |
| 3. First-order spread | The household loses its earner, borrows for lawyers and travel, and may withdraw children from school. The state keeps paying about ₹4,195 a month | NCRB spend (Derived). Household effects are mechanism only, not measured | Earlier release and earlier counsel |
| 4. System feedback | Overcrowding, less capacity for fair treatment, more adjournments, more pending cases | 120.8% occupancy in 2023, 112.7% in 2024 (NCRB). Over 5.6 crore pending (NJDG) | Cleaner listing and complete case papers |

**Two self-reinforcing loops.**
1. The people who are not identified are the ones least able to reach a lawyer on their own (7.91% used free legal aid in 2016–19), so they stay unidentified.
2. Each missed release adds to overcrowding, which makes the next committee review harder.

**Who bears the ripple.**

| Who | How it spreads | Measured evidence | Not yet quantified |
|---|---|---|---|
| **Households** | Loss of earner income, informal debt, school withdrawal | Litigants lose ₹50,387 crore a year across all case types (DAKSH 2015–16) | Income loss and debt per undertrial; effect on school dropout |
| **Women and dependants** | Women carry the household, and a jailed woman's dependants lose their carer | 1,049 women undertrials (2023); 514 of 1,416 recommended released (Q4 2025) | Effect on dependants of jailed women |
| **Society** | Unequal access to the law and loss of trust when a right does not reach those who need it | Legal aid reached about 0.15% of those entitled (Derived); literacy figures in 2.5 | Public trust (no survey exists) |
| **Prisons and courts** | Overcrowding, adjournments, growing backlog | 75.81% of inmates are undertrials; adjournments took 54% of civil and 33% of criminal sitting time (DAKSH 2016) | Share of adjournments caused by missing papers or advocate clashes; share of overcrowding caused by eligible people still held |
| **Economy** | Lost earnings, hearing costs and state custody spend | ₹50,387 crore and about ₹30,000 crore a year (2015–16); ₹2,669.88 crore on inmates (FY 2023–24) | Update to current prices; full institutional cost per inmate |

**The last column is itself a finding.** The largest costs, to households and public trust, are the least measured. We therefore put **no number on the ripples** beyond the direct custody floor in Section 4. A pilot that records household outcomes after release (income resumed, debt taken, children back in school) would add more to the evidence than another national statistic.

## 6. From evidence gap to feature to indicator

Each feature answers a specific gap shown above, and each writes an event we can count. Events hold counts and categories only, never identities.

| Evidence gap | Who must be equipped | Feature | What changes if it works | Indicator | Data source |
|---|---|---|---|---|---|
| Identification is 2.7% of prisoners | Court staff and legal-aid lawyers (the nightly check and the approval) | **Undertrial Watch** | Eligible people are listed with itemised dates and a draft application | People flagged; flagged people confirmed eligible by a lawyer; days over limit when flagged | `undertrial_flagged`, `release_application_approved` events; pilot log |
| 16% of recommended are not filed; 1,946 pending | Advocates and legal-aid lawyers (preparation), with a staff approval gate | Release application draft and human approval gate | Fewer applications stall for missing paperwork | Days from eligibility to filing | Pilot log (`days_over_limit`, `application_filed`) |
| Legal aid reaches about 0.15% of those entitled | Citizens and families (awareness and a ready application) | **Free legal aid check** (citizen) | People find out they qualify and get a drafted application | Checks, eligible results, applications drafted, partner-reported outcomes | `legal_aid_check`, `legal_aid_application`, `legal_aid_outcome` events |
| People cannot read or act on court papers | Citizens and families | **Understand a court document**, **Understand a legal problem**, **Know your rights** | Plain-language understanding without a lawyer | Documents analysed, citizen sessions, feedback ratings | `document_analyzed`, `citizen_session`, `feedback` events |
| Advocates lose hours on paper-books and long records | Advocates | **Document Studio**, **AI Document Insights**, **Chat with this document** | Faster preparation; claims that can be checked against the page | Pages handled, operations, insights, upload-to-result time (session); hours saved per case (pilot) | Advocate session counters; pilot log (`manual_minutes`, `tool_minutes`) |
| Adjournments eat 33% to 54% of sitting time | Court staff and registry | **Case triage and cause list** | Conflict-free, risk-sized listing; critical cases not left waiting | Cases triaged, cases listed, conflicts avoided, critical wait gained | `case_triaged`, `cause_list_published` events |
| Some cases need not go to trial | Court staff and registry | ADR routing | Suitable cases reach Lok Adalat or mediation | ADR candidates | `adr_candidate` event |
| No evidence of real-world use | All three groups | **Feedback wall** `/feedback` | Field users report what changed for them | Responses, average rating, share whose situation changed | `feedback` events; `/api/field-feedback` |

**Why no single group is enough.** The "who must be equipped" column shows that the leaks sit with different groups: awareness and a first application with citizens and families, preparation with advocates, and identification and listing with court staff. The funnel in Section 2.3 and the access gap in Section 2.4 are linked in both directions. People who are not identified are the least able to reach a lawyer on their own (loop 1 in Section 5), and a lawyer who reaches them still needs a registry that lists the case on time. A tool for one group moves the bottleneck to the next. This column is a mapping of where each gap sits, not a measured share of the problem owned by each group, and no pilot data yet shows how the three doors perform together.

**Design choices that protect the evidence.** Rules sit in code, so a result can be traced to its inputs. Every consequential output passes a human gate, and each approval is logged as a decision event. Insights and chat answers carry a page number and an excerpt that is checked against the extracted text, so a reviewer can verify any claim in seconds.

## 7. What is proven today, and what is not

| Evidence | What it shows | What it does not show |
|---|---|---|
| 21 hand-derived Section 479 cases (`tests/gold_479.json`) | The engine returns the expected status and dates for known inputs | Not verified by a lawyer yet. Not real cases |
| Offline unit and integration tests (`python -m unittest discover -s tests`) | Rules, grounding, workspace isolation, upload handling, scheduling invariants (no advocate double-booked, no bench over capacity, nothing lost) | Behaviour in a real court |
| Synthetic evaluation (`python scripts/eval_demo.py`) | The system behaves as designed on invented cases and courts | Real-world accuracy or impact |
| Session counters in the Advocate page | Real counts of pages, operations, documents and insights in one session | Time saved against a manual baseline |
| Impact log and feedback wall | The instrumentation is in place and counts-only | Any field outcome, until real users generate events |

**Claims we do not make.** We do not claim releases secured, custody days avoided, hours saved or households helped. The figures in Sections 1 to 5 describe the problem, not our results.

### Ethics and data handling

- Real case files are not uploaded to a hosted model without consent. Names and addresses are **not** masked, so only anonymised or invented documents go into the demo.
- Case references are anonymised and events never hold personal data.
- Household follow-up needs informed, voluntary consent and may be refused without any effect on help received.
- Every output is legal information for a lawyer to review, and nothing is filed without a human decision.


## 8. Sources

- [NALSA, Functioning of the Under Trial Review Committees, October to December 2025](https://cdnbbsr.s3waas.gov.in/s32e45f93088c7db59767efef516b306aa/uploads/2026/02/20260211666479586.pdf)
- [NCRB, Prison Statistics India 2023](https://www.ncrb.mha.gov.in/uploads/files/PSI-2023.pdf)
- [The News Minute / IndiaSpend on Prison Statistics India 2024](https://www.thenewsminute.com/news/dataviz-who-are-indias-371000-prisoners-awaiting-trial)
- [NCRB expenses on inmates by year (via Dataful)](https://dataful.in/datasets/23017)
- [DAKSH Access to Justice Survey, key findings](https://dakshindia.org/state-of-the-indian-judiciary/28-chapter-15.html)
- [Law Ministry reply on legal aid and LADCS, Lok Sabha, 13 March 2026 (reported by ANI)](https://newsable.asianetnews.com/india/over-166-lakh-get-free-legal-aid-in-fy-202526-law-ministry-articleshow-rsh2lwr)
- [India Justice Report 2025, national press release](https://indiajusticereport.org/files/English_National%20Press%20Release_India%20Justice%20Report%202025.docx05e1a2.pdf)
- [Bar & Bench: India's legal aid crisis, what the data really shows](https://www.barandbench.com/amp/story/columns/indias-legal-aid-crisis-what-the-data-really-shows)
- [Bar & Bench: Rajya Sabha reply on pendency, July 2026](https://www.barandbench.com/news/26-cases-pending-in-supreme-court-for-30-years-558-cases-for-20-years-centre-in-rajya-sabha)
- [Telangana Today / PTI: 5.64 crore cases pending, Rajya Sabha, 23 July 2026](https://telanganatoday.com/more-than-5-64-crore-cases-pending-across-indian-courts-rs)
- [Law Ministry reply, Lok Sabha, 13 February 2026: 5.39 crore pending (via Moneylife)](https://www.moneylife.in/article/court-case-pendency-rises-to-539-crore-supreme-court-sees-11-percentage-jump-in-one-year-govt/79667.html)
- [National Judicial Data Grid](https://njdg.ecourts.gov.in/)
- [ThePrint on Prison Statistics India 2023](https://theprint.in/india/drop-in-inmates-additions-but-indian-prisons-120-full-delhi-jails-most-overcrowded-at-200-ncrb-data/2754893)
- [Verdictum: Supreme Court order of 19 November 2024 on prolonged incarceration of undertrials](https://www.verdictum.in/court-updates/supreme-court/in-re-inhuman-conditions-in-1382-prisons-release-undertrial-prisoners-prolonged-incarceration-1559091)
- [Millennium Post: Section 479 releases](https://www.millenniumpost.in/nation/govt-over-330-undertrial-prisoners-released-on-bail-under-bnss-section-479-604985)