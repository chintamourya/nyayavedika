# 8-week simulation (SYNTHETIC data - not court results)

Command: `python scripts/simulate_8_weeks.py --initial 1500 --weekly 700 --weeks 8 --seed 42 --start 2026-11-02`; rules rules-v2; SLA working days {'Critical': 1, 'High': 5, 'Medium': 15, 'Routine': 30}; must-list after 3 deferrals; reserve 15%; aging cap 25.

| | With aging + must-list | Without (plain priority) |
|---|---|---|
| Cases seen | 6400 | 6400 |
| Still waiting at the end | 206 | 293 |
| Cases past deadline | 1 | 141 |
| Share deferred 3+ times (%) | 10.4 | 8.0 |
| Average utilisation (%) | 83.9 | 81.6 |
| Longest wait, Critical (days) | 1 | 1 |
| Longest wait, High (days) | 4 | 4 |
| Longest wait, Medium (days) | 22 | 31 |
| Longest wait, Routine (days) | 24 | 56 |

Model: listed cases leave the queue; unlisted ones are deferred; deadline clocks start when a case joins;
new filings every week from the same synthetic generator. It shows starvation and its fix, not real court
throughput. 5 benches x 300 minutes x 5 days per week, expected minutes sized by adjournment risk.
