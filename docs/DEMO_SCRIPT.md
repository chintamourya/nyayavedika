# Demo script: Timely Justice, 7 minutes

All data is synthetic. Before you start: `python scripts/reset_demo.py`, then `python server.py` (the intake worker runs inside it).
Give each role a different token in `.env` (`DEMO_TOKEN_STAFF`, `DEMO_TOKEN_LAWYER`, `DEMO_TOKEN_CITIZEN`).
Open http://127.0.0.1:8000/staff, paste the staff token top right. Citizens use /citizen (no login).
Staff lists show at most 10 synthetic examples per data kind; totals and cause-list operations still use the full dataset.

| Min | Click | Say | If the LLM or internet fails |
|---|---|---|---|
| 0:00 | **Today** | "Every morning the registry sees what is urgent and why: Critical waiting, release-eligible, past deadline, needs review. Each card has its reason." | Nothing here uses the LLM. |
| 1:00 | **Intake** -> drop 5 files from `sample_docs/` (`fir_01_theft.txt`, `fir_02_cheating.pdf`, `bail_01_application.pdf`, `order_01_bail_granted.pdf`, `custody_01_jail_certificate.txt`) -> Submit | "Five papers in, no typing. Watch each move: Uploaded, Reading, Summarising, Prioritising, Proposed hearing." | Offline mode reads and scores with rules and an extractive summary; say "this is the no-AI fallback". Takes about 3 seconds. |
| 2:30 | Open the custody certificate result | "Score, band and every reason in plain words. The Sec. 479 check flags an undertrial near the release threshold, with the page the date came from." | Same, rules only. |
| 3:30 | **Intake** -> drop the real High Court judgment (`WP 2163 2024`) | "A decided order is recognised as disposed: it never enters the hearing queue and is not scored as a person in custody." | Same, rules only. |
| 4:00 | **Cause list** -> 1 pick the week -> 2 check the draft (four numbers, one checks box, open "Why this order?") -> 3 Approve and publish | "Draft only: the Registrar approves. Every must-list case fits, no advocate clashes; oldest-first would double-book advocates." | Deterministic planner, no LLM. Uploaded cases carry an Uploaded badge. |
| 5:00 | **Undertrial** -> "Needs a decision": approve one, dismiss one (reason required) | "A lawyer decides. Nothing is filed by the system." | Deterministic; the draft says AI or Rules. |
| 5:45 | Open `/citizen` -> pick a language -> "Do I qualify for free legal aid?" -> answer -> **Draft application** -> download .docx | "A citizen gets a plain answer, where to go, and a ready application. No names are stored." | Rules engine and DOCX writer are offline. The draft text is a template instead of AI-written. |
| 6:45 | **Insights** | "Hours saved, deadlines met, eligible people helped. Synthetic data, labelled as such." | Deterministic. |

## One-line answers
- Is the AI deciding? No. Rules score and schedule; the model only reads and summarises; a human approves.
- Numbers? `docs/EVAL.md` (regenerate with `python scripts/eval_demo.py`). Synthetic data, not court results.
- Limits? Rules need lawyer review; one synthetic court; demo tokens are not real login; offline extraction is tuned to the sample layouts.
