"""Generic ReAct agent as a LangGraph StateGraph.

    START -> agent --(tool)--> tools -> agent
                   --(ask_user)--> ask_user [interrupt: waits for the person] -> agent
                   --(final)--> END

The LLM emits one typed `AgentStep` per turn (structured output), so tool selection works with
any model that supports JSON schemas. Clarifying questions use LangGraph `interrupt()`, so a
conversation can pause for hours (a paralegal fetching a document) and resume on the same thread.

With a `role` (Nyaya Mitra front door, Phase 7): an intent step narrows the tool list each turn; a tool
with side effects never runs on the model's say-so - the agent asks for a clear yes and runs it only on the
next turn when the person says yes; tools may return action cards; final answers get safety lines first
and, for citizens, the next step + helpline; offline, the deterministic FrontDoor handles the turn.
"""
import json
import logging
import operator
from typing import Annotated, Callable, Dict, List, Optional, TypedDict

from .. import config, llm
from ..models import AgentStep
from .context import context_block, facts_from_context
from .tools import CITIZEN, Tool, capabilities, catalogue, observation_text

logger = logging.getLogger(__name__)


def merge_steps(old: list, new: list) -> list:
    """Append steps; a leading "__reset__" marker starts a fresh per-turn trace."""
    if new and new[0] == "__reset__":
        return list(new[1:])
    return (old or []) + (new or [])


class AgentState(TypedDict, total=False):
    messages: Annotated[List[dict], operator.add]   # conversation: {"role", "content"}
    steps: Annotated[list, merge_steps]             # this turn's tool trace
    actions: Annotated[list, merge_steps]           # this turn's action cards [{label, route, prefill}]
    pending: Optional[dict]                         # action chosen by the agent node
    final: Optional[str]
    language: str
    allowed: Optional[List[str]]                    # tools picked by the intent step for this turn
    awaiting: Optional[dict]                        # hand-over waiting for the person's yes {tool, args}
    door: Optional[dict]                            # offline FrontDoor state
    batch_id: Optional[str]                         # files attached in this turn (intake batch)
    context: Optional[dict]                         # the 5-question guide's answers + result (see agents/context.py)


REACT_RULES = """
You work step by step. At each step output exactly one action:
- a tool name from the list, with action_input_json as a JSON object of arguments;
- "ask_user" with question_for_user when a fact you need is missing (ask ONE short question at a time);
- "final_answer" with final_answer when you can respond.
Rules:
- Use tools for eligibility, legal thresholds, case data and law - never compute or recall them from memory.
- Ground legal statements in tool results (search_law / web_search) and name the source.
- Never ask for or repeat names, phone numbers, Aadhaar, PAN or addresses; they are not needed.
- If the user asks what to do next, give useful general next steps immediately; missing details are not a reason to withhold them.
- Incorporate the user's answer to a clarifying question, and never repeat a question that has already been answered.
- Prefer at most {max_steps} tool calls per turn.
- Reply with ONE JSON object (the values, not a schema) with the keys thought, action, action_input_json,
  question_for_user, final_answer. Examples:
  {{"thought": "need the custody date", "action": "ask_user", "action_input_json": "{{}}", "question_for_user": "Since when is the person in custody?", "final_answer": null}}
  {{"thought": "check the limit", "action": "check_undertrial_release", "action_input_json": "{{\\"custody_since\\": \\"2024-03-01\\", \\"max_sentence_years\\": 7, \\"first_time_offender\\": true, \\"offence\\": \\"theft\\"}}", "question_for_user": null, "final_answer": null}}
  {{"thought": "done", "action": "final_answer", "action_input_json": "{{}}", "question_for_user": null, "final_answer": "..."}}

Available tools:
{tools}
"""


FRONT_DOOR_RULES = """
Front-door rules:
- Answer first, then the next step, in the explicitly selected language; it overrides the language the user writes in.
  If no language is selected, reply in the user's language. Do not mix languages or include a second-language version.
  Legal statements must come from a tool result or a
  cited passage (name the source); web facts must show the date they were checked.
- Never predict whether someone will win; explain options and legal aid instead.
- Hand-over tools (marked) change records or need a person's decision: propose them, the system asks for a clear yes.
{capabilities}"""


def _short(text, limit: int) -> str:
    text = str(text or "")
    return text if len(text) <= limit else text[:limit] + " ..."


def _recent(messages: List[dict]) -> List[dict]:
    """The last AGENT_HISTORY_MESSAGES turns, each cut to a readable length: a long chat (or a pasted document) must
    not push the request past the provider's per-minute token limit."""
    return [{**m, "content": _short(m["content"], config.AGENT_MESSAGE_CHARS)}
            for m in (messages or [])[-config.AGENT_HISTORY_MESSAGES:]]


def build_react_agent(system_prompt: str, tools: List[Tool], checkpointer=None,
                      offline_fallback: Optional[Callable[[AgentState], object]] = None, role: Optional[str] = None,
                      intent_fn: Optional[Callable[[str, bool], List[str]]] = None):
    from langgraph.graph import END, START, StateGraph
    from langgraph.types import interrupt

    by_name = {t.name: t for t in tools}
    ctx = {"role": role} if role else None

    def system_for(allowed: Optional[List[str]], context: Optional[dict] = None) -> str:
        chosen = [t for t in tools if not allowed or t.name in allowed] or tools
        extra = FRONT_DOOR_RULES.format(capabilities=capabilities(tools)) if role else ""
        return (system_prompt + context_block(context) + extra
                + REACT_RULES.format(tools=catalogue(chosen), max_steps=config.AGENT_MAX_STEPS))

    def _last_user(state) -> str:
        return next((m["content"] for m in reversed(state.get("messages", [])) if m["role"] == "user"), "")

    def _final(state, answer, extra: Optional[Dict] = None) -> dict:
        if role:
            from .front_door import finalise
            answer = finalise(answer, _last_user(state), role, facts_from_context(state.get("context")))
        language = state.get("language")
        if role == CITIZEN and language:
            answer = llm.enforce_language([answer], language)[0]
        return {"final": answer, "pending": None, "messages": [{"role": "assistant", "content": answer}], **(extra or {})}

    def _offline(state, note: str = "") -> dict:
        out = offline_fallback(state) if offline_fallback else "The assistant is offline (no LLM configured)."
        if isinstance(out, dict):  # FrontDoor result
            reply = note + out["reply"]
            return {"final": reply, "pending": None, "messages": [{"role": "assistant", "content": reply}],
                    "actions": ["__reset__"] + out.get("actions", []), "door": out.get("state")}
        return {"final": note + out, "pending": None, "messages": [{"role": "assistant", "content": note + out}]}

    def _model_failed(state, steps, exc) -> dict:
        """The model call failed (rate limit, too large, bad reply): this turn is still answered - from the tool
        results already gathered, else by the built-in guide. The next turn tries the model again."""
        logger.warning("agent model call failed (%s: %s); answering this turn without it", type(exc).__name__, str(exc)[:160])
        note = "(The AI assistant is busy right now, so this answer comes from the built-in guide.)\n\n"
        found = [s for s in steps if s.get("action") not in ("ask_user",) and s.get("observation")]
        plain = [s for s in found if not str(s["observation"]).lstrip().startswith(("{", "["))]   # not raw JSON
        if plain:   # readable tool results (e.g. a legal-aid passage) are still the best answer we have
            body = "\n\n".join(_short(s["observation"], 1200) for s in plain[-2:])
            return _final(state, note + "Here is what I found:\n\n" + body)
        try:   # raw JSON never reaches a person: the built-in guide writes plain sentences from the whole conversation
            return _offline(state, note)
        except Exception:
            logger.exception("built-in guide failed too")
        if found and role != "citizen":   # staff / lawyers may see the raw tool results
            body = "\n\n".join(_short(s["observation"], 1200) for s in found[-2:])
            return _final(state, note + "Here is what I found:\n\n" + body)
        return _final(state, note + "I could not finish this check just now. Please try again in a minute. If it is urgent, "
                                    "call the NALSA legal aid helpline 15100 (free) or 112 for immediate danger.")

    def agent(state: AgentState) -> dict:
        steps = [s for s in state.get("steps", []) if isinstance(s, dict)]
        if not llm.available():
            return _offline(state)
        update: Dict = {}
        awaiting = state.get("awaiting")
        if role and awaiting and not steps:  # the person's reply to "shall I ...?"
            from .front_door import _yes_no
            answer = _yes_no(_last_user(state))
            update["awaiting"] = None
            if answer is True:
                obs = by_name[awaiting["tool"]].run(ctx=ctx, confirmed=True, **awaiting["args"])
                steps = [{"thought": "user confirmed", "action": awaiting["tool"], "input": awaiting["args"],
                          "observation": observation_text(obs)}]
                update["steps"] = steps
                update["actions"] = obs.get("actions", []) if isinstance(obs, dict) else []
            elif answer is False:
                steps = [{"thought": "user declined", "action": awaiting["tool"], "input": {}, "observation": "user said no - nothing was done"}]
                update["steps"] = steps
        if role and intent_fn and not steps and state.get("allowed") is None:
            update["allowed"] = intent_fn(_last_user(state), bool(state.get("batch_id")))
        allowed = update.get("allowed", state.get("allowed"))
        if state.get("batch_id") and not steps and "analyze_document" in by_name:
            # Files came with this message: read them first, in code. The model then only explains what was read,
            # so a document is never skipped because the model picked another tool or passed a wrong batch id.
            obs = by_name["analyze_document"].run(ctx=ctx, batch_id=state["batch_id"])
            steps = [{"thought": "files are attached: read them first", "action": "analyze_document",
                      "input": {"batch_id": state["batch_id"]}, "observation": observation_text(obs)}]
            update["steps"] = steps
            if isinstance(obs, dict) and obs.get("actions"):
                update["actions"] = obs["actions"]
        if len(steps) >= config.AGENT_MAX_STEPS:
            return {**_finish(state, steps, "Step limit reached - answer with what you have."), **update}
        scratch = "\n".join(
            f"<step n='{i + 1}'>\nthought: {_short(s['thought'], 300)}\naction: {s['action']}({_short(str(s['input']), 300)})\n"
            f"observation: {_short(s['observation'], config.AGENT_OBSERVATION_CHARS)}\n</step>" for i, s in enumerate(steps))
        lang = state.get("language") or "the user's language"
        messages = _recent(state["messages"])
        messages.append({"role": "user", "content": f"<scratchpad>\n{scratch or '(no steps yet)'}\n</scratchpad>\n"
                                                    f"Decide the next action. Final answers must be in {lang}."})
        try:
            step = llm.structured_chat(system_for(allowed, state.get("context")), messages, AgentStep, fast=config.AGENT_FAST)
        except Exception as exc:
            return {**_model_failed(state, steps, exc), **update}
        if step.action == "final_answer":
            answer = (step.final_answer or "").strip()
            if not answer:  # never show the model's private reasoning: write the answer from the tool results instead
                return {**_finish(state, steps, "Write the final answer for the person now."), **update}
            return {**_final(state, answer), **update}
        if step.action == "ask_user":
            question = step.question_for_user or "Could you tell me more?"
            language = state.get("language")
            if role == CITIZEN and language:
                question = llm.enforce_language([question], language)[0]
            return {"pending": {"type": "ask_user", "question": question,
                                "thought": step.thought}, **update}
        if step.action not in by_name:
            if (step.final_answer or "").strip():  # an answer under an odd action name is still an answer
                return {**_final(state, step.final_answer.strip()), **update}
            # an unknown tool, or one this role may not use: tell the model and let it choose again (bounded by max steps)
            names = ", ".join(sorted(by_name))
            return {"pending": {"type": "invalid", "name": step.action, "args": {}, "thought": step.thought,
                                "note": f"'{step.action}' is not a tool you can use. Tools: {names}. "
                                        "Use one of them, ask_user, or final_answer."}, **update}
        try:
            args = json.loads(step.action_input_json or "{}")
        except json.JSONDecodeError:
            args = {}
        args = args if isinstance(args, dict) else {}
        tool = by_name[step.action]
        if role and tool.has_side_effects:  # hand-over: ask first, run only on the next turn's clear yes
            question = tool.confirm_question or f"Shall I go ahead with {tool.name.replace('_', ' ')}? (yes / no)"
            clean = {k: v for k, v in args.items() if k not in ("confirmed", "_ctx", "ctx")}
            card = {"label": question.split("?")[0] + "?", "route": "chat:confirm", "prefill": {"tool": tool.name, "args": clean}}
            return {**_final(state, (step.final_answer or "").strip() + ("\n\n" if step.final_answer else "") + question,
                             {"awaiting": {"tool": tool.name, "args": clean}, "actions": ["__reset__", card]})}
        return {"pending": {"type": "tool", "name": step.action, "args": args, "thought": step.thought}, **update}

    def _finish(state, steps, note):
        scratch = "\n".join(f"{s['action']}: {_short(s['observation'], config.AGENT_OBSERVATION_CHARS)}" for s in steps)
        lang = state.get("language") or "the user's language"
        msgs = _recent(state["messages"]) + [{"role": "user", "content": f"{note} Answer in {lang}.\nTool results:\n{scratch}"}]
        try:
            return _final(state, llm.chat(system_prompt + context_block(state.get("context")), msgs, fast=config.AGENT_FAST))
        except Exception as exc:
            return _model_failed(state, steps, exc)

    def tools_node(state: AgentState) -> dict:
        p = state["pending"]
        if p["type"] == "invalid":  # the model named a tool it does not have: record that and let it choose again
            return {"steps": [{"thought": p["thought"], "action": p["name"], "input": {}, "observation": p["note"]}],
                    "pending": None}
        args = {k: v for k, v in p["args"].items() if k not in ("confirmed", "ctx", "_ctx")}  # only a person's yes confirms
        tool = by_name[p["name"]]
        if tool.needs_file and state.get("batch_id"):
            args["batch_id"] = state["batch_id"]  # the files of this message, whatever id the model wrote
        obs = tool.run(ctx=ctx, **args)
        out = {"steps": [{"thought": p["thought"], "action": p["name"], "input": args,
                          "observation": observation_text(obs)}], "pending": None}
        if isinstance(obs, dict) and obs.get("actions"):
            out["actions"] = obs["actions"]
        return out

    def ask_user(state: AgentState) -> dict:
        p = state["pending"]
        answer = interrupt({"question": p["question"]})   # graph pauses here until resumed
        return {"messages": [{"role": "assistant", "content": p["question"]},
                             {"role": "user", "content": str(answer)}],
                "steps": [{"thought": p["thought"], "action": "ask_user", "input": {"question": p["question"]},
                           "observation": f"user answered: {answer}"}],
                "pending": None}

    def route(state: AgentState) -> str:
        p = state.get("pending")
        if not p:
            return END
        return "ask_user" if p["type"] == "ask_user" else "tools"

    g = StateGraph(AgentState)
    g.add_node("agent", agent)
    g.add_node("tools", tools_node)
    g.add_node("ask_user", ask_user)
    g.add_edge(START, "agent")
    g.add_conditional_edges("agent", route, {"tools": "tools", "ask_user": "ask_user", END: END})
    g.add_edge("tools", "agent")
    g.add_edge("ask_user", "agent")
    return g.compile(checkpointer=checkpointer)


def new_turn(message: str, language: str = "", batch_id: Optional[str] = None, context: Optional[dict] = None) -> dict:
    """Input for a new user turn on an existing (or new) thread. `context` (the guide's answers and result) is only
    written when given, so a later message without it keeps the one already on the thread; a fresh guide result
    replaces it."""
    return {"messages": [{"role": "user", "content": message}], "steps": ["__reset__"], "actions": ["__reset__"],
            "pending": None, "final": None, "allowed": None, "batch_id": batch_id,
            **({"language": language} if language else {}), **({"context": context} if context else {})}
