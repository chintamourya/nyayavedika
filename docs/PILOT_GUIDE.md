# Pilot guide: getting real impact data (rubric criterion 4)

Criterion 4 is 25 points and the tiebreaker. Synthetic data cannot score here. Real, anonymised cases can.

## Who to ask
A law-school legal-aid clinic, a District Legal Services Authority (DLSA), or an NGO doing prison legal aid.
Ask for one paralegal or lawyer for a few hours, and 20 to 50 anonymised undertrial files.

## What to do (a half-day pilot)
1. Pick 20 to 50 cases the clinic has already handled or is about to handle. Remove names; use a case reference only.
2. For each case, the clinician screens it **by hand** and notes the minutes taken (`manual_minutes`). Do this first, so the baseline is honest.
3. Run the same case through the tool. Note the minutes with the tool, including the lawyer's check (`tool_minutes`), and what the tool said (`tool_status`).
4. The lawyer records their own decision (`lawyer_verdict`).
5. For flagged people, record days past the limit, whether an application was filed and the outcome if known.
6. Copy `pilot/pilot_log_template.csv` to `pilot/pilot_log.csv`, fill one row per case, then run:

```
python scripts/pilot_report.py pilot/pilot_log.csv --write docs/PILOT_RESULTS.md
```

## Report it honestly
- Say how many cases, who ran the pilot, and when. Small and real beats large and invented.
- If you could not run a field pilot, report a **retrospective validation** instead and call it that.
- Never mix synthetic numbers into the pilot table. Keep the simulation under "quality of solution".
- Keep the log free of names, FIR numbers and prison details. Do not commit `pilot/pilot_log.csv` if it could identify anyone.
