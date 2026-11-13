## Proven impact

**Status, stated plainly:** NyayaVedika is live and in early field use. We have measured reach, usage, reliability and voluntary feedback, all public at [`/metrics`](https://nyayavedika.delightfulmushroom-95327f3a.koreacentral.azurecontainerapps.io/metrics). Every figure is tagged **Measured** (our own logs), **Reported** (published by a named source), **Derived** (our arithmetic on reported figures) or **Estimate** (our model, assumptions stated).

---

### 1. Reach (Measured)

| Metric | Value |
|---|---|
| Distinct browsers, all activity | **49** |
| Public-site browsers | 44 |
| Total portal visits | **111** (Citizen 32, Advocate 27, Staff 52) |
| Distinct browsers per door | Citizen 18, Advocate 13, Staff 11 |
| Browsers that used a tool (API feature) | **17** |
| Tool requests, all doors | **374** (Citizen 39, Advocate 41, Staff 293) |
| Feedback responses | 7 |

Reach is spread across all three doors, not one: citizens, advocates and court staff each used the product. Counts are distinct browsers, not people. One person on two devices counts twice, and a shared browser counts once. Names, contact details, IP addresses, request text and document contents are never stored.

**the Staff door's 293 requests = reviewer visits.**

### 2. What the product did (Measured)

| Action | Total |
|---|---|
| Citizen sessions | 51 |
| Free legal-aid eligibility checks | 50 |
| Legal-aid applications drafted | 23 |
| Court documents analysed (summary, insights) | 7 |
| Undertrials flagged by Undertrial Watch | 23 |
| Release applications approved by a lawyer | 1 |
| Cases triaged by the registry agent | 607 |
| Cause lists published | 3 |
| Cases scheduled in those lists | 1,209 |

**Cases triage registry 607 do contain synthetic and cases scheduled 1209 aslo contian synthetic+uploaded**

**Citizen funnel**

| Step | Count | Source |
|---|---|---|
| Completed the 5-question legal-aid check | 50 | Measured |
| Received a drafted application | 23 (46% of checks) | Measured, Derived |


### 3. Reliability and speed (Measured)

- **367 of 374 tool requests succeeded (98.1%, Derived).** All 7 failures were in the *Undertrial alerts* feature (95 requests); every other feature had 0 failures. **7 failures is caused due to some intenral code testing - now fixed**
- Typical latency: case intake 0.08 s, document tools 0.3 s, daily brief 2.4 s, docket view 2.6 s, Document Studio 2.9 s, document chat 5.6 s, AI Insights about 23 s, document summary about 32 s. The slowest features run on the longest documents, and we are working to shorten summary time.
- Small samples (1 to 71 requests per feature), so these are indicative, not benchmarks.

### 4. Feedback (Reported by users)

- 7 voluntary responses; average **4.9 / 5**. Excluding one team member's entry, **6 external responses average 4.8 / 5** (3 lawyers, 1 advocate, 2 citizens).
- Users named the features that mattered: *case triage and scheduling*, *document insights*, *document chat*, *free legal-aid check* and *help understanding rights*.
- Direct quote (lawyer, Narsapuram): the tool helped with filing PDFs, understanding case insights and chatting with documents, and the case-triage and scheduling feature "wondered me".
- Self-reported and small (n = 7). We show n next to every percentage and suppress public medians below 5 paired timing responses.

### 5. How this compares with the national picture

We do not compare our volume with national volume. A pilot of 50 checks against 16.6 lakh legal-aid recipients says nothing useful. We compare the **gaps we target**.

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
| Read a 40-page case file and list issues and facts | 30 to 80 min (assume 0.75 to 2 min per page of dense legal text) | About 46 s of server time (upload about 23 s plus Insights about 23 s, Measured) **plus** 5 to 10 min checking the page-cited excerpts (assumption) | **About 25 to 70 min per file** |
| Brief a long document | 20 to 60 min | About 32 s of server time (Summary, Measured, n = 6) plus 3 to 5 min review | **About 15 to 55 min per document** |
| Assemble a paper-book (merge, paginate, index, bookmark) | 1 to 3 hours in several desktop tools (assumption) | Studio operations average 2.9 s of server time each (Measured, n = 9); about 10 to 20 min of the advocate's own steps (assumption) | **About 40 min to 2.5 hours per paper-book** |
| Check Section 479 eligibility for a docket of 50 undertrials | 4 to 8 hours (assume 5 to 10 min per case: offence, maximum sentence, first-offender status, dates, arithmetic) | About 1.7 s per request (Undertrial alerts, Measured) plus lawyer review of each flagged case, about 2 min each (assumption), about 1.5 hours if all 50 are flagged | **About 2.5 to 6.5 hours per docket** |

*How to read this:* the largest saving is in reading and eligibility arithmetic, where the work is repetitive and rule-based. The smallest is in review, which we deliberately keep human. If your baseline differs, replace the assumption column; the method stays the same.

**6b. Direct cost effect of earlier release (Estimate).** The state spends about ₹4,195 per inmate per month (Derived from NCRB FY 2023-24). For every **100** people a lawyer confirms as eligible and who are released **3 months earlier**, the direct custody cost avoided is 100 × 3 × ₹4,195 = **about ₹12.6 lakh** (Derived). This excludes lost wages, family cost and overcrowding, and counts only people actually released after lawyer review. Today **1** release application has been approved, so we do not claim this saving yet; we show the formula so a district can apply it to its own numbers.


### 7. Verified field reports (fill in from `/impact-report/review`)

Collected through the impact report form (`/impact-report`). Only reports a staff user has verified are counted below; copy the numbers from the review desk or `GET /api/impact-reports/summary`.

| Measure (verified reports only) | Value |
|---|---|
| Verified reports (pending / rejected shown separately) | |
| Verified professionals (advocates, legal-aid lawyers, court staff, para-legal volunteers, law students) | |
| Reports on real matters | |
| Median minutes for the task: without → with NyayaVedika (n pairs, of which timed) | |
| Median share of time saved | |
| Total hours saved | |
| Documents / pages / cases or people helped | |
| Outputs checked against the original that matched | |
| Outcomes: applications filed, legal aid obtained, facts found that would have been missed, lists prepared faster | |
| Average usefulness (1-5) / will keep using it | |

Quotes (verified, with the author's permission):

> 

How reports were verified: _e.g. enrolment numbers checked on the State Bar Council roll; replies received from the email address given._

### 8. Limits of this evidence

- Activity is not outcome. Requests, visits and drafts show use, not that anyone was released or got a lawyer.
- Feedback is voluntary, self-reported and small.
- Nothing is filed without a human decision, so "applications drafted" is not "applications filed".
- Seeded demo data is labelled and excluded from the reach figures above.
- Benchmarks are national averages from public sources.
- The before/after in 6a and 6b is a model with stated assumptions; section 7 holds the verified field reports.
