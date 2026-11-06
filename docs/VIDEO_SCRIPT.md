# 2–3 minute demo video script

All data on screen is synthetic. Run `python scripts/reset_demo.py` first. Staff token and citizen page as in [DEMO_SCRIPT.md](DEMO_SCRIPT.md) (the 7-minute version).

| Time | Show | Say |
|---|---|---|
| 0:00–0:15 | Title card with 3 numbers | "5.8 crore cases pending. 75.8% of prisoners are undertrials. Most people entitled to free legal aid never reach a lawyer. NyayaVedika is five agents that help the offices already working on this." |
| 0:15–0:55 | `/citizen` → pick a language → "Do I qualify for free legal aid?" → answer → Draft application → download .docx | "A citizen gets a plain answer in their language, where to go, and a ready application." |
| 0:55–1:35 | `/staff` → Intake → drop `custody_01_jail_certificate.txt` and `fir_01_theft.txt` → open the result | "The Document Analyst reads the file and every date is checked against the source. The Section 479 check is plain code, not the LLM, and it flags someone near the release threshold." |
| 1:35–1:55 | Undertrial tab → approve one alert | "A lawyer decides. Nothing is filed by the system." |
| 1:55–2:20 | Cause list → Approve and publish | "Urgency-ranked, no advocate double-booked. The Registrar approves." |
| 2:20–2:45 | Insights tab, then the repo and deployment URL | "Every outcome is logged for impact reporting. Open source, MIT. Built with AgentFoundry." |
