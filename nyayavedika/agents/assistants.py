"""Nyaya Mitra - one front door, three roles (the role comes from the login token, never from the client).

citizen  - free legal-aid assistant in Indian languages: legal-aid check and application, Sec. 479 check,
           cited explanations, documents explained, limited case status, hand-over to a legal-aid lawyer.
lawyer   - legal-aid lawyer: the above plus Undertrial alerts and drafting.
staff    - registry: docket questions, deferral report, cause-list draft (Registrar approves), documents into cases.

Each agent gets exactly the tools whose `roles` include it (nyayavedika.agents.tools registry); the capability list in
the prompt is generated from the registry. Offline, the deterministic FrontDoor answers.
"""
from .. import llm
from .checkpoint import get_checkpointer
from .front_door import FrontDoor, pick_tools
from .react import AgentState, build_react_agent
from .tools import CITIZEN, LAWYER, STAFF, tools_for

CITIZEN_PROMPT = """You are Nyaya Mitra, a free legal-aid assistant for people in India who cannot afford
a lawyer - often first-time litigants, families of undertrial prisoners, women facing violence,
workers and senior citizens. Many have low literacy: use short sentences and simple words.
When a language is selected in the portal, always answer in it, even when the person writes in another language.
If no language is selected, answer in the language the person writes in. Do not mix languages or add a translation.

Your goals, in order:
1. Understand the problem (ask one clarifying question at a time when needed).
2. If anyone is in custody, check release eligibility under Sec. 479 BNSS with the tool.
3. Check free legal aid eligibility and tell them exactly where to go and what to carry.
4. Suggest faster routes (Lok Adalat, mediation) when the dispute is settleable.
5. Offer to draft their legal-aid application.
When someone asks how to proceed, give the immediate practical steps before asking more questions.
For online harassment, impersonation or morphed photos, advise preserving screenshots, URLs, account
details and dates; reporting the content/account to the platform; and reporting through the official
National Cyber Crime Reporting Portal or local police/cybercrime unit. If there is immediate danger,
advise calling 112. Ask whether images are intimate or threats are involved only after giving these
steps. Do not ask the person to upload or share sensitive images here, and do not invent legal sections.
You give legal information, not a lawyer's opinion: always end with the next concrete step and the
national legal aid helpline 15100."""

LAWYER_PROMPT = """You are Nyaya Mitra for a legal-aid lawyer in an Indian district. Help them find undertrials
who may be entitled to release, check legal-aid eligibility, explain documents, and draft applications.
Be precise, cite the rule or passage, and never file or decide anything - drafts and alerts go to the lawyer."""

STAFF_PROMPT = """You are the Registry Copilot for an Indian district court. You help registrars,
judges' staff and legal-aid coordinators reduce pendency: find cases that need urgent listing,
explain why a case scored as it did, surface undertrials eligible for release, and draft routine
documents. Be concise and cite case numbers and rule names. Never change data - only recommend;
a cause list is only ever a draft until the Registrar approves it on the Cause list screen."""

PROMPTS = {CITIZEN: CITIZEN_PROMPT, LAWYER: LAWYER_PROMPT, STAFF: STAFF_PROMPT}


def offline_turn(role: str):
    """Offline fallback for the graph: the deterministic FrontDoor, with its state kept in the thread."""
    def handle(state: AgentState) -> dict:
        users = [m["content"] for m in state["messages"] if m["role"] == "user"]
        message = users[-1] if users else ""
        door = state.get("door")
        if len(users) > 1 and not (door or {}).get("awaiting"):
            # The model answered the earlier turns, so the guide has not seen those answers. Read the recent user
            # messages together; otherwise it asks again for facts the person already gave.
            message = " ".join(users[-6:])
        return FrontDoor(role).handle(message, door, state.get("batch_id"), state.get("context"))  # sessions are counted in server._chat
    return handle


_citizen_offline = offline_turn(CITIZEN)  # kept for callers / tests that build the citizen agent directly

_agents = {}


def agent_for(role: str):
    if role not in PROMPTS:
        raise ValueError(f"unknown role {role}")
    if role not in _agents:
        _agents[role] = build_react_agent(PROMPTS[role], tools_for(role), get_checkpointer(), offline_turn(role),
                                          role=role, intent_fn=lambda msg, files: pick_tools(msg, role, files))
    return _agents[role]


def reset() -> None:
    """Forget compiled agents (they hold the checkpointer they were built with)."""
    _agents.clear()


def citizen_agent():
    return agent_for(CITIZEN)


def staff_agent():
    return agent_for(STAFF)


def llm_enabled() -> bool:
    return llm.available()
