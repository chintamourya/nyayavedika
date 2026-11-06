"""Pleading section drafting for legal-aid lawyers and registry (speeds up filing of
complete, defect-free papers - defects are a major cause of listing delays).

Prompt templates adapted from Case-Draft-Backend/source/prompts.py (prompts_dict) and the
generate_content() flow in Case-Draft-Backend/source/GenAI.py.
"""
from typing import Dict

from . import llm

_COMMON = """CRITICAL FORMATTING REQUIREMENTS:
- Use formal legal language appropriate for Indian court documents
- NO markdown formatting (no **, *, ---, etc.)
- NO generic conclusions or meta-commentary
- Use only facts provided in the context; leave [placeholders] for anything missing
"""

SECTIONS: Dict[str, Dict[str, str]] = {
    "list_of_dates": {
        "name": "List of Dates",
        "prompt": "Draft a \"List of Dates\" section.\n" + _COMMON + """- Chronological order, DD.MM.YYYY format, one material event per line
Example format:
01.01.2023    Event description
15.02.2023    Another relevant event
Generate only the chronological list of dates and events.""",
    },
    "facts": {
        "name": "Facts of the Case",
        "prompt": "Draft a \"Facts of the Case\" section.\n" + _COMMON + """- Numbered paragraphs (1., 2., 3.), chronological and objective, with dates and amounts
- Begin with "That the Petitioner submits as follows:"
Generate only the numbered paragraphs without any section header.""",
    },
    "grounds": {
        "name": "Grounds",
        "prompt": "Draft legal \"Grounds\".\n" + _COMMON + """- Structure as "GROUND 1:", "GROUND 2:" with numbered sub-paragraphs
- Each ground should cite the specific legal provision violated
Generate only the grounds.""",
    },
    "prayer": {
        "name": "Prayer",
        "prompt": "Draft a \"Prayer\" section.\n" + _COMMON + """- Begin with "In the premises aforesaid, it is most respectfully prayed that this Hon'ble Court may be pleased to:"
- Lettered sub-prayers (a), (b), (c); end with general relief and costs
Generate only the prayer.""",
    },
    "bail_application": {
        "name": "Bail Application",
        "prompt": "Draft a regular bail application for an Indian criminal court.\n" + _COMMON + """- Numbered paragraphs: custody details, facts, grounds for bail (period in custody, parity,
  completion of investigation / filing of charge sheet, no flight risk, Sec. 479 BNSS where applicable)
- End with a prayer and an undertaking to abide by conditions
Generate the application body only.""",
    },
    "adjournment_objection": {
        "name": "Objection to Further Adjournment",
        "prompt": "Draft a short memo objecting to a further adjournment.\n" + _COMMON + """- Numbered paragraphs citing the number of prior adjournments and the prejudice caused
- Refer to Order XVII Rule 1 CPC (limit of three adjournments) for civil matters where relevant
Generate only the memo body.""",
    },
}


def draft(section: str, context: str, instructions: str = "") -> Dict:
    spec = SECTIONS.get(section)
    if not spec:
        raise ValueError(f"Unknown section '{section}'. Choose from {list(SECTIONS)}")
    if not llm.available():
        return {"engine": "unavailable", "section": spec["name"],
                "text": "Drafting needs the LLM. Set the AZURE_OPENAI_* settings."}
    user = f"Here is the context for the draft:\n{context}\n\nThese are the user instructions to follow:\n{instructions or 'None'}"
    return {"engine": "llm", "section": spec["name"], "text": llm.text(spec["prompt"], user)}
