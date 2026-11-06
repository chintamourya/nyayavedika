"""Generate one SYNTHETIC multi-page Indian sessions-court case file (PDF) plus its ground truth.

    python scripts/make_case_file.py      -> sample_docs/case_file_01_cheating_sessions.pdf
                                             sample_docs/ground_truth/case_file_01_cheating_sessions.json

Scenario: Sec. 479 BNSS test. Offence BNS 318(4) (max 7 years). First-time offender in custody since 10.02.2024, so the
one-third rule is met on 10.06.2026 and the accused is release-eligible on the demo date. All names/numbers are invented.
Latin-1 only (the bundled PDF writer has no Telugu/Hindi fonts).
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from make_sample_docs import text_pdf, BANNER  # noqa: E402

NAME = "case_file_01_cheating_sessions"

P1 = f"""IN THE COURT OF THE II ADDITIONAL DISTRICT AND SESSIONS JUDGE, NTR DISTRICT AT VIJAYAWADA
CASE RECORD AND ORDER SHEET

Sessions Case No. 156 of 2024    Instituted on: 12.06.2024
Crime No. 118/2024 of Krishnalanka Police Station, Vijayawada
State of Andhra Pradesh, represented by the Public Prosecutor  vs.  Kondapalli Suresh Babu (A-1) and Tadikonda Ramesh (A-2)
Offence: BNS Section 318(4) (cheating and dishonestly inducing delivery of property), read with BNS Section 61(2)

INDEX OF THE CASE FILE
1. Police report summary (page 2)
2. Remand order dated 10.02.2024 (page 3)
3. Charge sheet particulars and list of witnesses (page 4)
4. Order sheet entries (page 5)
5. Prison particulars from the Superintendent (page 6)

CURRENT STATUS
The accused A-1 (Kondapalli Suresh Babu) has been in judicial custody since 10.02.2024. A-1 is a first-time offender and has no previous
conviction. A-2 is on bail. Charges were framed on 05.12.2024. The trial is at the stage of prosecution evidence.
Stage: Prosecution evidence.
Adjourned to 20.11.2026 for evidence of PW-5 (bank manager).
Sessions Judge
"""

P2 = """POLICE REPORT SUMMARY
Police Station: Krishnalanka, Vijayawada, NTR District.   Date of FIR: 14.01.2024
Complainant: Shri P. Raghava Rao, retired bank employee, resident of Governorpet, Vijayawada.
Allegation: Between 02.11.2023 and 09.01.2024 the accused Kondapalli Suresh Babu (A-1) represented himself as the proprietor of a firm dealing in
agricultural exports and induced the complainant to transfer Rs. 14,60,000 in four instalments to a current account of the
firm, promising a share of the profit. No export business was found to exist. The cheque issued by the accused towards
refund, dated 05.01.2024, was returned unpaid.
Investigation: The Station House Officer arrested A-1 on 09.02.2024 from a lodge near the railway station. Bank statements
and the account opening form were seized under a panchanama. A-2 (Tadikonda Ramesh), the account holder, was not arrested and obtained
regular bail from this court.
Signed: Station House Officer, Krishnalanka P.S.
"""

P3 = """REMAND ORDER
Before the Judicial Magistrate of First Class (Mobile Court), Vijayawada.   Date: 10.02.2024
The accused A-1 was produced at 11:40 hours with the remand report. The Magistrate informed him of the grounds of arrest and
of his right to a lawyer from the District Legal Services Authority panel. The accused did not engage a private lawyer.
The offence is under BNS Section 318(4). Police custody is not sought. The accused is remanded to judicial custody on
10.02.2024 up to 24.02.2024 and shall be produced through video link on the next date. The remand is extended from time to
time.
Magistrate
"""

P4 = """CHARGE SHEET PARTICULARS
Charge sheet filed on 28.04.2024 before the Judicial Magistrate of First Class; committed to the Court of Session on 12.06.2024.
Offences charged: BNS Section 318(4); BNS Section 61(2) (criminal conspiracy) against A-1 and A-2.
Maximum punishment for the principal offence: imprisonment up to seven years and fine.
Witnesses cited: 14 (PW-1 complainant; PW-2 and PW-3 panch witnesses; PW-4 bank clerk; PW-5 bank manager; PW-6 to PW-13
other bank and telecom officials; PW-14 investigating officer).
Documents: 31 (bank statements, account opening form, returned cheque memo, panchanama, arrest memo).
Evidence recorded so far: PW-1 to PW-4. PW-5 summoned several times; bank manager transferred to another district.
"""

P5 = """ORDER SHEET ENTRIES
05.12.2024: Charges framed under BNS Section 318(4) and BNS Section 61(2). Accused pleaded not guilty. Case posted for
prosecution evidence.
18.03.2025: PW-1 examined in chief. Adjourned to 22.05.2025 for cross-examination. Accused in judicial custody since
10.02.2024, produced through video link.
22.05.2025: Cross-examination of PW-1 not completed. Counsel for accused seeks time. Adjourned to 14.08.2025.
14.08.2025: PW-1 cross-examination completed. PW-2 and PW-3 examined. Adjourned to 30.10.2025.
30.10.2025: PW-4 examined. PW-5 not present, summons returned unserved. Adjourned to 12.02.2026.
12.02.2026: Public Prosecutor reports that PW-5 has been transferred. Fresh summons through the Superintendent of Police.
Adjourned to 25.06.2026.
25.06.2026: PW-5 absent again. Warrant issued. Adjourned to 17.09.2026. Stage: Prosecution evidence.
17.09.2026: PW-5 absent. Prosecution seeks last opportunity. Adjourned to 20.11.2026 for evidence of PW-5.
Sessions Judge
"""

P6 = """OFFICE OF THE SUPERINTENDENT, DISTRICT PRISON, VIJAYAWADA
CUSTODY CERTIFICATE
Certified that undertrial prisoner UTP No. 5518, Kondapalli Suresh Babu, accused A-1 in Sessions Case No. 156 of 2024 on the file of the
II Additional District and Sessions Judge, NTR District, has been in judicial custody in this prison continuously from
10.02.2024 to date. The offence is under BNS Section 318(4). No previous conviction or other pending case is recorded in the
prison history ticket. Conduct in prison: satisfactory.
This certificate is issued for the purpose of an application under Section 479 BNSS.
Superintendent
"""

if __name__ == "__main__":
    out = ROOT / "sample_docs"
    n = text_pdf([P1, P2, P3, P4, P5, P6], out / f"{NAME}.pdf")
    gt = {"doc_type": "order", "case_type": "criminal_trial", "stage": "evidence", "filing_date": "2024-06-12",
          "accused_in_custody": True, "custody_since": "2024-02-10", "act": "BNS", "section": "318(4)",
          "case_number": "S.C. 156/2024", "synthetic": True, "file": f"{NAME}.pdf", "pages": n,
          "first_time_offender": True, "next_hearing_date": "2026-11-20"}
    (out / "ground_truth" / f"{NAME}.json").write_text(json.dumps(gt, indent=2), encoding="utf-8")
    print(f"wrote {NAME}.pdf ({n} pages) and ground truth")
