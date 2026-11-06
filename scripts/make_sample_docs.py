"""Generate 10 SYNTHETIC demo case documents plus ground truth for extraction scoring (Phase 3).

    python scripts/make_sample_docs.py            -> sample_docs/*.txt|pdf, sample_docs/ground_truth/<name>.json

Mix: 3 FIRs (one as a scanned image-PDF), 2 orders, 2 petitions, 2 bail / custody papers, 1 long record
(60+ pages of filler with the real facts on a few pages). One petition has no filing date on purpose
(ground truth filing_date = null -> the pipeline must say needs_review, never guess).
English only: Hindi / Telugu were skipped (no bundled fonts). All names and numbers are invented.
Text PDFs come from the small writer below (stdlib only); the scan needs Pillow.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sample_docs"
BANNER = "SYNTHETIC DEMO DOCUMENT - not a real case. All names, numbers and events are invented."


# ----------------------------------------------------------------------------- minimal text-PDF writer
def _pdf_escape(s: str) -> str:
    return s.encode("latin-1", "replace").decode("latin-1").replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")


def _wrap(text: str, width: int = 92):
    for para in text.splitlines():
        line = ""
        for word in para.split(" "):
            if line and len(line) + 1 + len(word) > width:
                yield line
                line = word
            else:
                line = f"{line} {word}" if line else word
        yield line


def text_pdf(pages, path: Path, lines_per_page: int = 52) -> int:
    """Write an uncompressed Helvetica text PDF. `pages` is a list of page texts (long pages overflow onto new ones)."""
    page_lines = []
    for text in pages:
        lines = list(_wrap(text))
        page_lines += [lines[i:i + lines_per_page] for i in range(0, max(len(lines), 1), lines_per_page)]
    objs = {1: "<< /Type /Catalog /Pages 2 0 R >>", 3: "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"}
    kids = []
    for i, lines in enumerate(page_lines):
        page_id, content_id = 4 + 2 * i, 5 + 2 * i
        stream = "BT /F1 10 Tf 50 800 Td 14.5 TL " + " ".join(f"({_pdf_escape(l)}) Tj T*" for l in lines) + " ET"
        objs[content_id] = f"<< /Length {len(stream.encode('latin-1'))} >>\nstream\n{stream}\nendstream"
        objs[page_id] = (f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] "
                         f"/Resources << /Font << /F1 3 0 R >> >> /Contents {content_id} 0 R >>")
        kids.append(f"{page_id} 0 R")
    objs[2] = f"<< /Type /Pages /Kids [{' '.join(kids)}] /Count {len(kids)} >>"
    out, offsets = bytearray(b"%PDF-1.4\n"), {}
    for n in sorted(objs):
        offsets[n] = len(out)
        out += f"{n} 0 obj\n{objs[n]}\nendobj\n".encode("latin-1")
    xref = len(out)
    out += f"xref\n0 {len(objs) + 1}\n0000000000 65535 f \n".encode()
    out += "".join(f"{offsets[n]:010d} 00000 n \n" for n in sorted(objs)).encode()
    out += f"trailer\n<< /Size {len(objs) + 1} /Root 1 0 R >>\nstartxref\n{xref}\n%%EOF\n".encode()
    path.write_bytes(bytes(out))
    return len(page_lines)


def scanned_pdf(text: str, path: Path) -> int:
    """Render text onto a slightly rotated grey page image and save it as an image-only PDF (needs OCR)."""
    from PIL import Image, ImageDraw, ImageFilter, ImageFont
    font = None
    for name in ("DejaVuSans.ttf", "arial.ttf", "Arial.ttf"):
        try:
            font = ImageFont.truetype(name, 26)
            break
        except OSError:
            continue
    font = font or ImageFont.load_default()
    img = Image.new("L", (1240, 1754), 245)
    draw = ImageDraw.Draw(img)
    y = 90
    for line in _wrap(text, 70):
        draw.text((90, y), line, fill=25, font=font)
        y += 36
    img = img.rotate(0.6, fillcolor=245).filter(ImageFilter.GaussianBlur(0.6))
    img.convert("RGB").save(path, "PDF", resolution=150)
    return 1


# ----------------------------------------------------------------------------- documents
def truth(doc_type, case_type, stage, filing_date, accused_in_custody, custody_since, act, section, case_number=None):
    return {"doc_type": doc_type, "case_type": case_type, "stage": stage, "filing_date": filing_date,
            "accused_in_custody": accused_in_custody, "custody_since": custody_since, "act": act, "section": section,
            "case_number": case_number, "synthetic": True}


FIR_THEFT = f"""{BANNER}
FIRST INFORMATION REPORT (Under Section 173 BNSS)
District: Hyderabad    Police Station: Saidabad    FIR No.: 0412/2026    Date of FIR: 14.03.2026
Act and Section: BNS Section 303(2) (Theft)
Complainant: Shri K. Venkat (synthetic), shopkeeper, Saidabad.
Details: On 13.03.2026 at about 21:30 hours an unknown person removed a cash box containing Rs. 18,500 from the
complainant's shop. On 15.03.2026 the accused A-1 (name withheld in demo) was arrested near the bus depot and the
cash box was recovered. The accused was produced before the Magistrate and remanded to judicial custody on 15.03.2026.
Status: Accused in judicial custody since 15.03.2026. Investigation in progress.
Signed: Station House Officer, Saidabad P.S."""

FIR_CHEATING = f"""{BANNER}
FIRST INFORMATION REPORT (Under Section 173 BNSS)
District: Rangareddy    Police Station: Gachibowli    FIR No.: 0977/2025    Date of FIR: 02.09.2025
Act and Section: BNS Section 318(4) (Cheating and dishonestly inducing delivery of property)
Complainant: Smt. P. Lakshmi (synthetic).
Details: The complainant paid Rs. 4,20,000 between 05.06.2025 and 20.07.2025 to the accused for an overseas job
placement that never existed. The accused stopped answering calls after 25.07.2025.
Status: Accused not arrested; granted anticipatory bail by the Sessions Court. The accused is not in custody."""

FIR_ROBBERY_SCAN = f"""{BANNER}
FIRST INFORMATION REPORT
District: Warangal   Police Station: Hanamkonda   FIR No. 0233/2026
Date of FIR: 21.01.2026
Act and Section: BNS Section 309 (Robbery)
On 20.01.2026 two persons on a motorcycle snatched a gold chain and a mobile phone from the complainant at knife point.
Accused A-1 and A-2 arrested on 23.01.2026 and remanded to judicial custody the same day.
Status: Both accused in judicial custody since 23.01.2026."""

ORDER_BAIL = f"""{BANNER}
IN THE COURT OF THE METROPOLITAN SESSIONS JUDGE, HYDERABAD
Criminal Miscellaneous Petition No. 1186 of 2026 (Bail)
Filed on: 04.05.2026
Between: Accused A-1 (Petitioner) and State of Telangana through SHO, Malakpet P.S. (Respondent)
Offence: BNS Section 305 (Theft in a dwelling house)
ORDER (pronounced on 18.05.2026)
The petitioner has been in judicial custody since 10.04.2026. The investigation is complete and the charge sheet
has been filed. Recovery has been effected. Considering the period of detention, the petition is allowed.
The petitioner shall be released on bail on executing a personal bond of Rs. 20,000 with two sureties.
Sessions Judge (synthetic)"""

ORDER_ADJOURN = f"""{BANNER}
IN THE COURT OF THE I ADDITIONAL SESSIONS JUDGE, KARIMNAGAR
Sessions Case No. 88 of 2024    Instituted on: 11.07.2024
State of Telangana vs. Accused A-1 (synthetic)
Offence: NDPS Act Section 20(b)(ii)(C) - commercial quantity of ganja
ORDER SHEET
17.10.2026: Case called for evidence. PW-4 (investigating officer) absent. The accused, in judicial custody since
02.05.2024, produced through video link. Prosecution seeks time. Adjourned to 07.11.2026 for evidence of PW-4.
Stage: Prosecution evidence.
Sessions Judge (synthetic)"""

PETITION_MAINTENANCE = f"""{BANNER}
IN THE COURT OF THE JUDGE, FAMILY COURT, HYDERABAD
M.C. No. 3410 of 2026    Date of filing: 09.06.2026
Petition under Section 144 of the Bharatiya Nagarik Suraksha Sanhita, 2023 (maintenance)
Petitioner: Smt. R. Sunitha (synthetic), aged 31, and minor child.  Respondent: Husband (name withheld in demo).
1. The petitioner was married to the respondent on 14.02.2018. She was sent out of the matrimonial home in 2025.
2. The respondent earns about Rs. 45,000 per month and has refused to maintain the petitioner and the minor child.
PRAYER: Direct the respondent to pay Rs. 15,000 per month as maintenance to the petitioner and the child.
Advocate for the petitioner (synthetic)"""

PETITION_CHEQUE_NO_DATE = f"""{BANNER}
IN THE COURT OF THE SPECIAL JUDICIAL MAGISTRATE OF FIRST CLASS (NI ACT CASES), HYDERABAD
Complaint under Section 138 of the Negotiable Instruments Act, 1881
Complainant: M/s Sri Sai Traders (synthetic).  Accused: Proprietor, M/s Ganesh Hardware (synthetic).
1. The accused issued cheque No. 004512 for Rs. 2,75,000 towards supply of goods.
2. The cheque was returned unpaid with the remark "funds insufficient". A legal notice was issued and received;
   no payment was made within fifteen days.
PRAYER: Take cognizance under Section 138 NI Act and punish the accused in accordance with law.
(The filing stamp on this copy is not legible.)"""

BAIL_APPLICATION = f"""{BANNER}
IN THE COURT OF THE XI ADDITIONAL CHIEF METROPOLITAN MAGISTRATE, HYDERABAD
Crl. M.P. No. 2290 of 2026 in Crime No. 0518/2026 of Banjara Hills P.S.    Filed on: 12.08.2026
APPLICATION FOR REGULAR BAIL UNDER SECTION 480 BNSS
Offence alleged: BNS Section 318(4) (Cheating)
1. The applicant (synthetic) was arrested on 28.07.2026 and has been in judicial custody since 29.07.2026.
2. The applicant is a first-time accused with no previous criminal record, and the entire evidence is documentary.
PRAYER: Release the applicant on bail on such conditions as this Hon'ble Court deems fit.
Counsel for the applicant (synthetic)"""

CUSTODY_CERT = f"""{BANNER}
OFFICE OF THE SUPERINTENDENT, CENTRAL PRISON, CHERLAPALLI
CUSTODY CERTIFICATE
Certified that undertrial prisoner UTP No. 7731 (synthetic), accused in Sessions Case No. 241 of 2023 on the file of the
IV Additional Sessions Judge, Rangareddy (case instituted on 19.09.2023), for the offence under BNS Section 117(2)
(voluntarily causing grievous hurt), has been in judicial custody in this prison continuously from 03.08.2023 to date.
The trial is at the stage of prosecution evidence.
This certificate is issued for the purpose of an application under Section 479 BNSS.
Superintendent (synthetic)"""


def long_record():
    cover = f"""{BANNER}
IN THE COURT OF THE PRINCIPAL SESSIONS JUDGE, MEDCHAL-MALKAJGIRI
Sessions Case No. 17 of 2022    Instituted on: 24.03.2022
State of Telangana vs. Accused A-1 and A-2 (synthetic)
Offence: BNS Section 103 (Murder)
CERTIFIED COPY OF THE CASE RECORD (Volume I)"""
    filler = ("Deposition of prosecution witness PW-{n}, recorded in open court. Examination-in-chief: The witness "
              "stated that he knows the accused and deposed about the events at the locality. Cross-examination: "
              "The witness denied the suggestion that he is deposing falsely. Re-examination: Nil. "
              "Read over and admitted correct. (Filler text for a long synthetic record.)\n") * 4
    pages = [cover]
    for n in range(2, 64):
        if n == 31:
            pages.append("REMAND AND CUSTODY PARTICULARS\nAccused A-1 arrested on 02.01.2022 and in judicial custody "
                         "continuously since 03.01.2022. Accused A-2 on bail since 15.06.2022.")
        elif n == 62:
            pages.append("PROCEEDINGS DATED 14.10.2026\nProsecution and defence evidence closed. Heard arguments of the "
                         "learned Public Prosecutor in part. Stage: arguments. Call on 28.10.2026 for defence arguments.")
        else:
            pages.append(filler.format(n=n))
    return pages


DOCS = [
    ("fir_01_theft.txt", "txt", FIR_THEFT,
     truth("fir", "criminal_trial", "admission", "2026-03-14", True, "2026-03-15", "BNS", "303", "FIR 0412/2026")),
    ("fir_02_cheating.pdf", "pdf", FIR_CHEATING,
     truth("fir", "criminal_trial", "admission", "2025-09-02", False, None, "BNS", "318", "FIR 0977/2025")),
    ("fir_03_robbery_scanned.pdf", "scan", FIR_ROBBERY_SCAN,
     truth("fir", "criminal_trial", "admission", "2026-01-21", True, "2026-01-23", "BNS", "309", "FIR 0233/2026")),
    ("order_01_bail_granted.pdf", "pdf", ORDER_BAIL,
     truth("order", "bail", "pronouncement", "2026-05-04", True, "2026-04-10", "BNS", "305", "Crl.M.P. 1186/2026")),
    ("order_02_adjournment.txt", "txt", ORDER_ADJOURN,
     truth("order", "criminal_trial", "evidence", "2024-07-11", True, "2024-05-02", "NDPS Act", "20", "S.C. 88/2024")),
    ("petition_01_maintenance.pdf", "pdf", PETITION_MAINTENANCE,
     truth("petition", "maintenance", "admission", "2026-06-09", None, None, "BNSS", "144", "M.C. 3410/2026")),
    ("petition_02_cheque_no_date.txt", "txt", PETITION_CHEQUE_NO_DATE,
     truth("petition", "cheque_bounce", "admission", None, None, None, "NI Act", "138", None)),
    ("bail_01_application.pdf", "pdf", BAIL_APPLICATION,
     truth("bail_custody", "bail", "admission", "2026-08-12", True, "2026-07-29", "BNS", "318", "Crl.M.P. 2290/2026")),
    ("custody_01_jail_certificate.txt", "txt", CUSTODY_CERT,
     truth("bail_custody", "criminal_trial", "evidence", "2023-09-19", True, "2023-08-03", "BNS", "117(2)", "S.C. 241/2023")),
    ("long_01_sessions_record.pdf", "long", None,
     truth("order", "criminal_trial", "arguments", "2022-03-24", True, "2022-01-03", "BNS", "103", "S.C. 17/2022")),
]


def main(out: Path = OUT) -> list:
    (out / "ground_truth").mkdir(parents=True, exist_ok=True)
    made = []
    for name, kind, text, gt in DOCS:
        path = out / name
        if kind == "txt":
            path.write_text(text + "\n", encoding="utf-8")
            pages = 1
        elif kind == "pdf":
            pages = text_pdf([text], path)
        elif kind == "scan":
            pages = scanned_pdf(text, path)
        else:
            pages = text_pdf(long_record(), path)
        (out / "ground_truth" / f"{Path(name).stem}.json").write_text(
            json.dumps({**gt, "file": name, "pages": pages}, indent=2) + "\n", encoding="utf-8")
        made.append((name, pages))
    return made


if __name__ == "__main__":
    for name, pages in main(Path(sys.argv[1]) if len(sys.argv) > 1 else OUT):
        print(f"{name:36s} {pages:3d} page(s)")
