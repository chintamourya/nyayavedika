"""Talk to Nyaya Mitra: a failing model call (429 / 413 / bad JSON) still answers the turn, and the prompt stays small.

The agent node is called directly through a stub StateGraph, so this runs without LangGraph installed.
"""
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import config, llm, store  # noqa: E402
from nyayavedika.agents import front_door  # noqa: E402
from nyayavedika.agents import tools as T  # noqa: E402


class _Graph:
    def __init__(self, _state):
        self.nodes = {}

    def add_node(self, name, fn):
        self.nodes[name] = fn

    def add_edge(self, *a):
        pass

    def add_conditional_edges(self, *a):
        pass

    def compile(self, checkpointer=None):
        return self


def _stub_langgraph():
    graph = types.ModuleType("langgraph.graph")
    graph.StateGraph, graph.START, graph.END = _Graph, "__start__", "__end__"
    lt = types.ModuleType("langgraph.types")
    lt.interrupt = lambda payload: "yes"
    return {"langgraph": types.ModuleType("langgraph"), "langgraph.graph": graph, "langgraph.types": lt}


class Failing:
    def __init__(self):
        self.calls = []

    def structured(self, model, system, messages, schema, **kw):
        self.calls.append({"model": model, "messages": messages, "schema": schema.__name__})
        raise RuntimeError("Error code: 429 - Too Many Requests")

    def text(self, *a, **kw):
        raise RuntimeError("Error code: 429 - Too Many Requests")


class AgentResilienceTests(unittest.TestCase):
    def setUp(self):
        self.old_db = config.DATABASE_URL
        config.DATABASE_URL = f"sqlite:///{tempfile.mkdtemp()}/t.db"
        store.prepare_database()
        self.backend = Failing()
        llm.set_backend(self.backend)
        with mock.patch.dict(sys.modules, _stub_langgraph()):
            from nyayavedika.agents.assistants import offline_turn
            from nyayavedika.agents.react import build_react_agent
            self.graph = build_react_agent("x", T.tools_for("citizen"), None, offline_turn("citizen"), role="citizen",
                                           intent_fn=lambda m, f: front_door.pick_tools(m, "citizen", f))

    def tearDown(self):
        llm.set_backend(None)
        config.DATABASE_URL = self.old_db

    def test_rate_limited_model_still_answers_from_the_guide(self):
        out = self.graph.nodes["agent"]({"messages": [{"role": "user", "content": "Am I eligible for a free lawyer?"}],
                                         "steps": [], "allowed": None})
        self.assertIsNone(out["pending"])
        self.assertIn("built-in guide", out["final"])
        self.assertEqual([c["schema"] for c in self.backend.calls].count("AgentStep"), 1)  # one try, no loop
        self.assertEqual(self.backend.calls[0]["model"], llm._models()[1])  # fast model for chat steps

    def test_tool_results_are_shown_when_the_model_fails_after_a_tool(self):
        steps = [{"thought": "t", "action": "legal_aid_kb_search", "input": {},
                  "observation": "Women are entitled to free legal aid under Section 12(c). [source: NALSA]"}]
        out = self.graph.nodes["agent"]({"messages": [{"role": "user", "content": "free lawyer for women?"}],
                                         "steps": steps, "allowed": ["legal_aid_kb_search"]})
        self.assertIn("Section 12(c)", out["final"])

    def test_long_history_is_trimmed(self):
        history = [{"role": "user" if i % 2 == 0 else "assistant", "content": "x" * 5000} for i in range(30)]
        self.graph.nodes["agent"]({"messages": history, "steps": [], "allowed": None})
        sent = self.backend.calls[0]["messages"]
        self.assertLessEqual(len(sent), config.AGENT_HISTORY_MESSAGES + 1)
        self.assertTrue(all(len(m["content"]) <= config.AGENT_MESSAGE_CHARS + 600 for m in sent))

    def test_tool_pick_needs_no_model_call(self):
        picked = front_door.pick_tools("Am I eligible for a free lawyer?", "citizen")
        self.assertIn("check_legal_aid_eligibility", picked)
        self.assertEqual(self.backend.calls, [])


if __name__ == "__main__":
    unittest.main()
