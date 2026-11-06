# UI walkthrough: the 7-minute demo path

First clicked through on 25 Oct 2026 against `scripts/dev_api.py` (scratch SQLite, 600 synthetic cases, offline mode).
The Cause list, Undertrial and legal-aid guide sections were re-checked on 3 Nov 2026 with the smaller seed (120 synthetic
cases + 1 uploaded FIR), after those screens were simplified. Every number is synthetic data.
Staff lists now show at most 10 synthetic examples per data kind. This is a display-only cap: totals and scheduling still use
the full dataset, and uploaded/imported records remain visible.

Every staff tab has a legend at the top: **Synthetic** (generated demo cases), **Uploaded** (from files you sent),
**AI** (written by the language model - check it) and **Rules** (fixed rules / template). Today, Docket, Cause list and
Insights say how many pending cases are synthetic and how many are real.

## Run it (one command each)

| What | Full requirements installed | Demo machine without FastAPI / LangGraph |
|---|---|---|
| API + frontend | `python server.py`, then open http://127.0.0.1:8000 | `python scripts/dev_api.py`, then open http://127.0.0.1:8010 (same pages, same role checks, offline assistant) |
| Worker | `python -m nyayavedika.worker` | built into `dev_api.py` (background thread) |
| Seed data | `python scripts/seed_demo.py` (120 cases; `DEMO_SEED_CASES`) | automatic when the docket is empty (`--seed 120`) |

Tokens come from `.env` (`DEMO_TOKEN_STAFF`, `DEMO_TOKEN_LAWYER`). The citizen portal needs no token: with no token, a citizen endpoint treats the caller as an anonymous citizen (`ANONYMOUS_CITIZEN=true` in demo mode).

## 1. Today (staff)
`/staff` → paste the staff token (top right). The board shows (each card has its reason underneath):

| Counter | Value |
|---|---|
| Critical waiting | 12 |
| Release-eligible | 3 |
| Past deadline | 0 |
| Needs review | 48 |
| Uploaded today | 0 |
| Deferred 3+ times | 21 |

Clicking a counter opens the Docket with that filter. "Do next" lists the fast-lane slots to accept, the cases needing one field, and the Undertrial link.

## 2. Intake
- Drop zone, plus "Choose folder" (a sub-folder named like a case number, e.g. SC-88-2024, becomes that case; otherwise pick "Each sub-folder is one case") and a paste-text box.
- Accepted: PDF and .txt (scanned images come back with OCR). A `.docx` or `.png` shows "✖ File type … is not accepted" beside
  its name; a PDF over 50 pages is refused with "the demo limit is 50 pages per file".
- Re-sending a file whose reading failed queues it again; only a file being read right now is reported as
  "Already in the system and still being processed (batch …)".
- With 6 files: "6 of 5 files - too many: remove some", and Submit is disabled.
- After Submit, each row moves through **Uploaded → Reading → Summarising → Prioritising → Proposed hearing** (polling every 2 s).

Results in this run:

| File | Result | Score | Reasons | Card |
|---|---|---|---|---|
| FIR, custody since 2023 | ‼ Critical | 58.4 | base +12, pending +11, custody +15, "Custody 1382d exceeds Sec. 479 BNSS threshold (547d) +20" | 📅 Proposed hearing 2026-10-27 10:30 on CR-1; Open case / Correct field / Accept slot |
| FIR, recent | ○ Routine | 28.8 | - | slot "not needed" |
| Cheque complaint without a date | Routine | - | - | "⚠ Needs review: Fill in filing date". Filling 2026-02-10 in the dialog re-scored it ("✓ complete") and wrote the audit log. |

## 3. Open a Critical case (drawer)
"Open case" opens a side drawer (Esc closes it):
- **Brief:** the 3-line glance. Each fact has "p. 1 · confidence 0.85 · source page"; the button shows the exact FIR page text.
- **Priority:** reasons as chips with their points (+12, +11, +15, +20), the flag UNDERTRIAL RELEASE ELIGIBLE, and the rules version.
- **Timeline:** date, event, and source document + page.
- **Documents:** label "extractive", the glance, the one-page brief, and a low-OCR warning when relevant.
- **History:** hearings (adjourned in court) and deferrals by the scheduler, kept apart.

## 4. Cause list
Three steps, shown as a strip at the top: **1 Pick the week → 2 Check the draft → 3 Approve and publish**.

1. Week starting (Monday) → "Prepare draft".
2. The draft card shows four numbers (3 Nov run: **121 cases listed** - 1 uploaded · 120 synthetic; **23/23 must-list cases
   fitted**; **0 carried** to a later week; **15.7%** bench time used), then one box: either "✓ All checks pass" or
   "Check before approving" with each problem (here: "4 critical case(s) cannot be listed by their deadline").
   "Why this order? Compare with listing oldest-first" is folded away (critical wait, advocate double-bookings, hearings
   expected to go ahead, cases listed). Each day is a section (the first is open) with one box per bench: utilisation bar,
   then time · band · case number, an **Uploaded** badge on real cases, and "must-list · deferred N×" where it applies.
   Clicking a case opens "Move to…" (day, bench) or "Hold this case"; a move to a full bench is refused.
3. "Approve and publish" → "Published: N hearing(s) created". Each case gets its next hearing date.

## 5. Undertrial (lawyer token)
- One screen, no status filter. The top card explains the path: Found → Lawyer approves → Filed in court → Heard → Released.
- **Needs a decision (N)** and **In progress (N)**. Each card: case number, Synthetic / Uploaded badge, "‼ 277 days over the
  limit", "1554 days in custody · legal limit 1277 days", and one main button: "Approve - file a release application"
  (lawyer; staff see "Waiting for a legal-aid lawyer to approve"), then "Mark as filed in court" / "Mark as heard" /
  "Mark as released". "Download application (Word)" is always there.
- "Read the draft application [AI | Rules] and the checklist" and "Not needed? Dismiss" (reason required) are folded away.
- "Missing information (N case(s))" is collapsed at the bottom: custody cases missing a fact, and who can supply it.
- "Check again now" (staff) runs the scan: "Checked: 1 new, 1 need information."

## 6. Citizen portal (`/citizen`, no login, phone width 375 px: no sideways scrolling)
- The language buttons switch the fixed text (Telugu: "న్యాయ మిత్ర - ఉచిత న్యాయ సహాయం"). 🎤 shows only when the browser supports speech input; 🔊 "read aloud" is on every answer.
- Hindi selected, "My brother has been in jail since March 2022 for theft.":
  1. Urgent numbers come first (112, 15100), then one question: first offence? The answer is offered as हाँ / नहीं buttons.
  2. "नहीं" gives: custody 1699 days against a Sec. 479 BNSS limit of 547 days; legal aid likely (Sec. 12(g)); "Shall I send these facts to a legal-aid lawyer for review?"
  3. "हाँ" gives: "Sent. Reference REQ/2026/…", then the next step + 15100.
- "Am I eligible?" (woman, Warangal):
  - ✔ Likely eligible for a free lawyer, because Sec. 12(c) - Woman
  - Where to go: DLSA Warangal, phone, labelled as a demo directory entry
  - What to carry, and the income-limit note
  - **What this means for you**: an explanation built from the rules' result and passages from the legal-aid index
    (`scripts/ingest_legal_aid.py`), marked AI or Rules, with numbered sources (3 Nov offline run: "Who are Entitled to Free
    Legal Services?", nalsa.gov.in, primary). With a model configured, one fast call writes it in the chosen language.
  - **Draft my application** asks for the problem in a few lines (no names or numbers), then shows the draft (Template or
    AI draft) with Copy and Download (Word).
- Chat "I earn 12,000 a month" gives "Likely eligible … Sec. 12(h) … Rs. 1,44,000", with the **Download application (Word)** action card.

## 7. Insights
- Longest wait per band, share deferred 3+, past deadline, utilisation of the latest list (70.9%), capacity shortfall, and impact counters with CSV export.
- On `dev_api` the impact counters show 0 with a note, because the impact log needs SQLAlchemy.
- The first card is "Synthetic / real cases" for the pending docket; the other docket figures mix both.

## Known limits seen in the walkthrough
- **Offline answers are in English.** The portal says so; with an LLM key, chat replies follow the chosen language.
- **"Longest wait" is long for the seeded backlog.** It counts from `first_eligible_on`, which is the filing date for seeded cases.
- **Lunch shows in slot spans.** A slot that crosses lunch shows the break in its time range, e.g. 13:29-14:34.
