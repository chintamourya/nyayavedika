## Proven impact

**Status, stated plainly:** NyayaVedika is live and in early field use. We have measured reach, usage, reliability and voluntary feedback, all public at [`/metrics`](https://nyayavedika.delightfulmushroom-95327f3a.koreacentral.azurecontainerapps.io/metrics). Every figure is tagged **Measured** (our own logs), **Reported** (published by a named source), **Derived** (our arithmetic on reported figures) or **Estimate** (our model, assumptions stated).

---

### 1. Reach (Measured)

| Metric | Value |
|---|---:|
| Distinct browsers, all activity | **59** |
| Public-site browsers | 49 |
| Portal visits | **223** (Citizen 38, Advocate 61, Staff 124) |
| Distinct browsers by door | Citizen 18, Advocate 17, Staff 17 |
| Browsers that used an API feature | **25** |
| Tool requests | **1,136** (Citizen 48, Advocate 149, Staff 935, 4 role unresolved) |
| Voluntary feedback responses | **7** |

Reach is spread across all three doors, not one: citizens, advocates and court staff each used the product. Counts are distinct browsers, not people. One person on two devices counts twice, and a shared browser counts once. Names, contact details, IP addresses, request text and document contents are never stored. The Staff door's 935 requests include reviewer visits.

### 2. What the product did (Measured)

| Product action | Measured total |
|---|---:|
| Citizen sessions | 53 |
| Completed five-question free legal-aid checks | 52 |
| Legal-aid applications drafted | 26 |
| Court documents analysed (summary or insights) | 13 |
| Undertrials flagged by Undertrial Watch | 25 |
| Release applications approved in the app | 7 |
| Cases triaged by the registry agent | 613 |
| Cause lists published | 4 |
| Cases scheduled in those lists | 1,216 |

Triaged and scheduled case totals include synthetic demo data as well as uploaded cases.

**Citizen funnel**

| Step | Count | Source |
|---|---|---|
| Completed the 5-question legal-aid check | 52 | Measured |
| Received a drafted application | 26 (50% of checks) | Measured, Derived |

### 3. Reliability and speed (Measured)

- **1,122 of 1,136 tool requests succeeded (98.8%, Derived).** The 14 logged failures sit in three features: Undertrial alerts 9 of 355 requests, case management 4 of 53, hearing management 1 of 43. Seven earlier failures were attributed to internal code testing and have been fixed; the cause of the remaining failures is still being reviewed. Every other feature had no logged failures.
- Typical server latency: case intake 0.06 seconds; document tools 0.5 seconds; undertrial alerts 1.7 seconds; docket view 2.2 seconds; Document Studio 2.0 seconds; daily brief 2.8 seconds; document chat 5.0 seconds; document upload 16.5 seconds; AI Insights about 22 seconds; document summary about 29 seconds; hearing management about 53 seconds on average (n = 43).
- Samples are small (2–355 requests per feature). Latencies are indicative server processing times, not end-to-end task times or benchmark results. Longer documents account for slower summary features; summary and hearing-management time remain improvement areas.

### 4. Feedback and reviewer input (Reported by users)

- Seven voluntary responses averaged **4.9/5**. Excluding one team member, six external responses (three lawyers, one advocate and two citizens) averaged **4.8/5**.
- **Ease of use:** 7 of 7 rated it 5/5. **Answer quality (self-rated):** 3 "correct and clear", 4 "mostly correct". **Would recommend:** 7 of 7.
- **What changed for them (self-reported):** 6 of 7 said they understood their rights better; 5 of 7 reached legal aid or a lawyer; 5 of 7 saved time; 4 of 7 said a case moved faster.
- **Time saved on their task (self-reported):** 2 under 1 hour, 3 between 1 and 3 hours, 2 a day or more. All three lawyers reported savings of 1 hour or more.
- **Features users named:** case triage and scheduling, document insights, document chat, document summary, the free legal-aid check and the rights guide.
- **Quotes.** A lawyer in Narsapuram said the tool helped with filing PDFs, understanding case insights and chatting with documents, and that case triage and scheduling "wondered me". A lawyer in Noida said they loved case triage and scheduling. A lawyer in Kurnool said understanding cases got easier.
- **Direct reviewer feedback (lawyer, by message).** After testing the app, a lawyer reported it "working so well" and liked the workflow and how intuitive it is. They found the page references in AI document insights accurate, said the "nature of dispute" line in the case background was vague, and recommended highlighting the source context from which each issue is identified so it can be verified faster. We have logged that as the next improvement.
- Feedback is self-reported, voluntary and small (n = 7). It shows that reviewers found the tool useful and its page references accurate; it is not independent verification of outcomes, and no lawyer has certified or approved the product.

**What feedback changed in our roadmap.** (1) Highlight the exact passage behind each Insights issue so a lawyer can verify it in one click (lawyer review, Nov 2026). (2) Tighten the "nature of dispute" line in the case background (same review). (3) Allow longer document summaries (lawyer feedback, Kurnool).

### 5. How this compares with the national picture

We do not compare our volume with national volume. A pilot of 52 checks against 16.6 lakh legal-aid recipients says nothing useful. We compare the **gaps we target**.

| Gap | National figure (source, type) | What NyayaVedika does about it |
|---|---|---|
| **Courts: backlog** | 5.64 crore pending cases as of 16 Jul 2026 (Law Ministry, NJDG; Reported) | Triage with reasons; conflict-free cause list sized by adjournment risk |
| **Counsel unavailable** | 35% of ~1.39 crore pending district-court criminal cases were delayed for want of counsel (NJDG, Jul 2026; Reported) | Free legal-aid check and a drafted application; Advocate door speeds a lawyer's file reading |
| **Undertrials not identified** | 14,387 identified (2.70% of 5,31,949 prisoners); 5,864 released (NALSA UTRC, Oct to Dec 2025; Reported). About 41% of identified were released (Derived) | Nightly Section 479 check with itemised arithmetic and a drafted application, so identification does not depend on a quarterly meeting |
| **Long detention** | 3,71,440 undertrials; 60,130 held over 2 years; about 9,000 over 5 years (NCRB PSI 2024; Reported) | Flags eligible people for a lawyer to approve |
| **Legal-aid reach** | 16,60,249 people in FY25-26 to Jan 2026, about 0.15% of the ~110 crore eligible (Law Ministry; IJR 2025; Reported, Derived) | Citizen door in English, Hindi and Telugu, no login |

**Benchmarks we plan to be measured against:** share of flagged undertrials a lawyer confirms as eligible, compared with the national identified-to-released rate of about 41%; and time to assemble or read a case file, manual versus with the tool.



### 6. Before and after

**6a. Modelled comparison (Estimate, not a field measurement).** Tool times come from our logs (Measured). Manual times are **our stated assumptions**, not observed. We show a range and include the human review time a lawyer still needs, because nothing is acted on without it. Server time is not end-to-end task time.

| Task | Before: manual (assumption) | After: with NyayaVedika | Estimated saving |
|---|---|---|---|
| Read a 40-page file and list issues/facts | 30–80 min | About 39 s server time (upload about 17 s plus Insights about 22 s) plus 5–10 min review | About 25–70 min |
| Brief a long document | 20–60 min | About 29 s server time plus 3–5 min review | About 15–55 min |
| Assemble a paper-book | 1–3 hours | Studio operations average 2.0 s server time each plus 10–20 min user steps | About 40 min–2.5 hours |
| Check Section 479 eligibility for a 50-person docket | 4–8 hours | About 1.7 s per request plus assumed lawyer review | About 2.5–6.5 hours |

*How to read this:* the largest saving is in reading and eligibility arithmetic, where the work is repetitive and rule-based. The smallest is in review, which we deliberately keep human. If your baseline differs, replace the assumption column; the method stays the same.

**6b. Direct cost effect of earlier release (Estimate).** The state spends about ₹4,195 per inmate per month (Derived from NCRB FY 2023-24). For every **100** people a lawyer confirms as eligible and who are released **3 months earlier**, the direct custody cost avoided is 100 × 3 × ₹4,195 = **about ₹12.6 lakh** (Derived). This excludes lost wages, family cost and overcrowding, and counts only people actually released after lawyer review. Today **7** release applications have been approved in the app, so we do not claim this saving yet; we show the formula so a district can apply it to its own numbers.


### 7. Field feedback summary (self-reported, from the feedback wall)

Source: the public feedback wall (`/feedback`), 7 voluntary responses collected 6–11 Nov 2026. Figures are the respondents' own reports and have not been independently verified. Reports staff verify through `/impact-report/review` are counted separately and are not included here.

| Measure | Value |
|---|---|
| Responses (lawyers / advocates / citizens) | 7 (3 / 1 / 3, of which 1 citizen entry is from the team) |
| Average rating | 4.9 / 5 (4.8 / 5 excluding the team member) |
| Would recommend | 7 of 7 |
| Reported a positive change | 7 of 7 |
| Understood their rights better | 6 of 7 |
| Reached legal aid or a lawyer | 5 of 7 |
| Saved time | 5 of 7 |
| A case moved faster | 4 of 7 |
| Time saved, self-reported | 2 under 1 hour; 3 of 1–3 hours; 2 a day or more |
| Answer quality, self-rated | 3 correct and clear; 4 mostly correct |

Direct lawyer review (by message): found the app working well, the workflow intuitive and the AI Insights page references accurate; recommended highlighting the source context of each identified issue and tightening the "nature of dispute" line.

### 8. Limits of this evidence

- Activity is not outcome. Requests, visits and drafts show use, not that anyone was released or got a lawyer.
- Feedback is voluntary, self-reported and small.
- Nothing is filed without a human decision, so "applications drafted" is not "applications filed".
- Seeded demo data is labelled and excluded from the reach figures above.
- Benchmarks are national averages from public sources.
- The before/after in 6a and 6b is a model with stated assumptions; section 7 holds self-reported feedback, not verified outcomes.
- No lawyer, bar body or court has certified or approved the product; feedback shows reviewers found it useful and its page references accurate.