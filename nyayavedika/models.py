"""Pydantic models for structured LLM output - every agent decision is validated."""
from typing import List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


# ------------------------------------------------------------------ document analysis
class CaseDetails(BaseModel):
    case_number: Optional[str] = None
    court_name: Optional[str] = None
    petitioners: List[str] = []
    respondents: List[str] = []
    judges: List[str] = []
    date_of_order: Optional[str] = None


class TimelineEvent(BaseModel):
    date: str = Field(description="DD.MM.YYYY")
    event: str
    para_reference: str = ""
    page: Optional[int] = Field(None, description="Source page, from the [page N] markers")


class NoteItem(BaseModel):
    text: str
    page: Optional[int] = Field(None, description="Source page, from the [page N] markers")
    para_reference: str = ""


class Issue(BaseModel):
    issue: str = Field(description="Framed as a legal question, e.g. 'Whether ...'")
    key_points: List[str] = []
    decision: Optional[str] = None
    para_reference: str = ""


class TriageSignals(BaseModel):
    custody: bool = False
    custody_since: Optional[str] = Field(None, description="YYYY-MM-DD if stated")
    max_sentence_years: Optional[str] = Field(None, description="number of years, or 'life' / 'death'")
    bail_matter: bool = False
    senior_citizen_party: bool = False
    woman_or_child_party: bool = False
    compoundable_or_settleable: bool = False
    next_hearing_date: Optional[str] = None
    urgency_reason: Optional[str] = None

    @field_validator(
        "custody",
        "bail_matter",
        "senior_citizen_party",
        "woman_or_child_party",
        "compoundable_or_settleable",
        mode="before",
    )
    @classmethod
    def default_null_flags_to_false(cls, value):
        return False if value is None else value


class CaseAnalysis(BaseModel):
    case_details: CaseDetails = CaseDetails()
    document_type: Literal["judgment", "interim order", "petition", "charge sheet", "FIR", "bail order", "other"] = "other"
    timeline: List[TimelineEvent] = []
    issues: List[Issue] = []
    statutes_cited: List[str] = []
    precedents_cited: List[str] = []
    outcome: Optional[str] = None
    directions_and_deadlines: List[str] = []
    plain_language_summary: str = ""
    triage_signals: TriageSignals = TriageSignals()

    @field_validator("document_type", mode="before")
    @classmethod
    def normalize_document_type(cls, value):
        if isinstance(value, str):
            aliases = {"order": "interim order", "fir": "FIR", "bail_custody": "bail order"}
            return aliases.get(value.strip().lower(), value)
        return value


class ChunkNotes(BaseModel):
    """Notes from one part (map) or a merged group of parts (reduce). Every item keeps its page reference."""
    dated_events: List[TimelineEvent] = []
    issues_raised: List[NoteItem] = []
    statutes: List[NoteItem] = []
    precedents: List[NoteItem] = []
    decisions_or_directions: List[NoteItem] = []
    custody_or_bail_facts: List[NoteItem] = []
    parties_and_prayer: List[NoteItem] = []


class DocTypeGuess(BaseModel):
    doc_type: Literal["fir", "order", "petition", "bail_custody", "other"]


class ClaimCheck(BaseModel):
    claim: str
    supported: bool
    evidence: str = Field("", description="Short verbatim quote from the source supporting the claim, or empty")


class VerificationReport(BaseModel):
    checks: List[ClaimCheck] = []
    overall_grounded: bool = True
    corrections: List[str] = Field([], description="Specific fixes the writer must make")


# ------------------------------------------------------------------ agents
class AgentStep(BaseModel):
    # No docstring and no Field(description=...) on purpose: small models (gpt-oss-20b) echo the schema's
    # descriptions back instead of an instance ("Field required: action"). The field guide lives in
    # react.REACT_RULES with a concrete example.
    thought: str = ""
    action: str
    action_input_json: str = "{}"
    question_for_user: Optional[str] = None
    final_answer: Optional[str] = None


class IntakeClassification(BaseModel):
    case_type: str
    stage: str = "admission"
    accused_in_custody: bool = False
    custody_since: Optional[str] = None
    max_sentence_years: Optional[str] = None
    senior_citizen: bool = False
    woman_or_child: bool = False
    disability: bool = False
    act: Optional[str] = None
    section: Optional[str] = None
    summary: str = ""


class ScoreAdjustment(BaseModel):
    case_id: str
    adjustment: int = Field(description="Between -10 and +10")
    reason: str
    missing_data: List[str] = []


class RegistryReview(BaseModel):
    adjustments: List[ScoreAdjustment] = []
    data_quality_notes: List[str] = []
