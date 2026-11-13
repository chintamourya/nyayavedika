"""Phase 1: roles, config, release zip, citizen privacy. Runs with no API keys and no .env.

    python -m unittest discover -s tests
"""
import ast
import importlib.util
import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from nyayavedika import auth, config  # noqa: E402

TOKENS = {"staff": "t-staff-123", "lawyer": "t-lawyer-456", "citizen": "t-citizen-789"}
HAS_SERVER_DEPS = all(importlib.util.find_spec(m) for m in ("fastapi", "httpx", "sqlalchemy", "langgraph"))


def _set_tokens(staff=TOKENS["staff"], lawyer=TOKENS["lawyer"], citizen=TOKENS["citizen"]):
    config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN = staff, lawyer, citizen


def _status(key, token):
    try:
        auth.check(f"Bearer {token}" if token else None, *auth.POLICY[key])
        return 200
    except auth.AuthError as exc:
        return exc.status


class RoleMatrixTests(unittest.TestCase):
    MATRIX = {  # endpoint -> (staff, lawyer, citizen)
        "GET /api/cases": (200, 403, 403),
        "POST /api/schedule": (200, 403, 403),
        "POST /api/registry/decide": (200, 403, 403),
        "GET /api/impact": (200, 403, 403),
        "GET /api/alerts": (200, 200, 403),
        "GET /api/alerts/{alert_id}/superintendent.docx": (200, 403, 403),
        "POST /api/alerts/decide": (403, 200, 403),
        "POST /api/documents/analyze": (200, 200, 403),
        "POST /api/documents/summarize": (200, 200, 200),
        "POST /api/legal-problem/research": (403, 403, 200),
        "POST /api/legal-problem/chat": (403, 403, 200),
        "POST /api/advocate/workspaces": (403, 200, 403),
        "POST /api/advocate/documents": (403, 200, 403),
        "POST /api/advocate/documents/{doc_id}/preview": (403, 200, 403),
        "POST /api/advocate/documents/{doc_id}/insights": (403, 200, 403),
        "POST /api/advocate/documents/{doc_id}/chat": (403, 200, 403),
        "POST /api/advocate/documents/{doc_id}/chat/prepare": (403, 200, 403),
        "POST /api/advocate/studio": (403, 200, 403),
        "POST /api/legal-aid/ask": (200, 200, 200),
        "POST /api/legal-aid": (200, 200, 200),
        "POST /api/agent/chat": (200, 200, 200),
    }

    def setUp(self):
        self.old = (config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN)
        _set_tokens()

    def tearDown(self):
        _set_tokens(*self.old)

    def test_matrix(self):
        for key, expected in self.MATRIX.items():
            got = tuple(_status(key, TOKENS[r]) for r in ("staff", "lawyer", "citizen"))
            self.assertEqual(got, expected, key)

    def test_unauthenticated_cases_is_401(self):
        self.assertEqual(_status("GET /api/cases", None), 401)
        self.assertEqual(_status("POST /api/legal-problem/research", None), 200)

    def test_citizen_cannot_decide_alerts(self):
        self.assertEqual(_status("POST /api/alerts/decide", TOKENS["citizen"]), 403)

    def test_bad_token_and_bad_scheme(self):
        self.assertEqual(_status("POST /api/legal-aid", "nope"), 401)
        with self.assertRaises(auth.AuthError) as ctx:
            auth.check(f"Basic {TOKENS['staff']}", *auth.ALL_ROLES)
        self.assertEqual(ctx.exception.status, 401)

    def test_unset_token_disables_role(self):
        _set_tokens(citizen="")
        self.assertEqual(_status("POST /api/legal-aid", TOKENS["citizen"]), 401)
        with self.assertRaises(auth.AuthError):
            auth.resolve("Bearer ")

    def test_principal_records_actor(self):
        p = auth.resolve(f"Bearer {TOKENS['lawyer']}")
        self.assertEqual((p.role, p.actor), ("lawyer", "demo-lawyer"))

    def test_shared_demo_token_uses_portal_role_within_policy(self):
        _set_tokens("mourya", "mourya", "mourya")
        for key, role in (
            ("GET /api/cases", auth.STAFF),
            ("POST /api/advocate/workspaces", auth.LAWYER),
            ("POST /api/legal-problem/research", auth.CITIZEN),
            ("POST /api/legal-problem/chat", auth.CITIZEN),
        ):
            principal = auth.check(
                "Bearer mourya", *auth.POLICY[key], role_hint=role
            )
            self.assertEqual(principal.role, role, key)
            self.assertEqual(principal.actor, f"demo-{role}", key)

    def test_demo_tokens_are_distinct_by_default(self):
        self.assertNotEqual(config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER)
        self.assertNotEqual(config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_CITIZEN)
        self.assertNotEqual(config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN)

    def test_role_hint_cannot_change_a_distinct_token_role(self):
        principal = auth.check(
            f"Bearer {TOKENS['lawyer']}", *auth.ALL_ROLES, role_hint=auth.STAFF
        )
        self.assertEqual(principal.role, auth.LAWYER)


class EveryEndpointGuardedTests(unittest.TestCase):
    """Static check of server.py: each /api route carries guard("<METHOD> <path>") and that key is in POLICY."""

    def test_routes_have_matching_guard(self):
        tree = ast.parse((ROOT / "server.py").read_text(encoding="utf-8"))
        seen = set()
        for fn in (n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)):
            for dec in fn.decorator_list:
                if not (isinstance(dec, ast.Call) and isinstance(dec.func, ast.Attribute)
                        and getattr(dec.func.value, "id", None) == "app" and dec.args
                        and isinstance(dec.args[0], ast.Constant) and str(dec.args[0].value).startswith("/api/")):
                    continue
                key = f"{dec.func.attr.upper()} {dec.args[0].value}"
                seen.add(key)
                if key in auth.PUBLIC:
                    continue
                self.assertIn(key, auth.POLICY, f"{key} has no role policy")
                guards = [c.args[0].value for c in ast.walk(ast.Module(body=[dec, fn.args], type_ignores=[]))
                          if isinstance(c, ast.Call) and getattr(c.func, "id", None) == "guard"
                          and c.args and isinstance(c.args[0], ast.Constant)]
                self.assertEqual(guards, [key], f"{fn.name} must use guard({key!r}) exactly once")
        self.assertEqual(set(auth.POLICY), seen - auth.PUBLIC, "POLICY lists a route server.py does not have")


class CitizenPrivacyTests(unittest.TestCase):
    def test_citizen_tools_have_no_lookup_case(self):
        from nyayavedika.agents.tools import CITIZEN_TOOLS, STAFF_TOOLS  # the registry needs no LangGraph
        names = [t.name for t in CITIZEN_TOOLS]
        self.assertIn("lookup_case", [t.name for t in STAFF_TOOLS])
        self.assertTrue(names)
        self.assertNotIn("lookup_case", names)


class ConfigTests(unittest.TestCase):
    def test_demo_defaults(self):
        self.assertEqual(config.DEMO_MAX_FILES, 5)
        self.assertEqual(config.MAX_UPLOAD_BYTES, config.DEMO_MAX_FILE_MB * 1024 * 1024)
        self.assertEqual(set(config.ALLOWED_EXTS), {"pdf", "txt"})  # images return with OCR
        self.assertEqual(config.SLA_DAYS, {"Critical": 1, "High": 5, "Medium": 15, "Routine": 30})
        self.assertEqual((config.MUST_LIST_RESERVE, config.MUST_LIST_AFTER_DEFERRALS, config.AGING_CAP), (0.15, 3, 25))
        self.assertEqual((config.WORKER_CONCURRENCY, config.MAP_PART_TOKENS, config.SINGLE_PASS_TOKENS), (2, 3000, 12000))
        self.assertEqual(config.PINECONE_LEGALAID_NAMESPACE, "legal_aid_kb")
        self.assertEqual(config.MAX_FILES_PER_FOLDER, 2)
        self.assertLessEqual(config.DEMO_MAX_PAGES, 50)


class ReleaseZipTests(unittest.TestCase):
    def setUp(self):
        spec = importlib.util.spec_from_file_location("make_release_zip", ROOT / "scripts" / "make_release_zip.py")
        self.mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(self.mod)

    def test_secrets_and_runtime_data_excluded(self):
        inc = self.mod.should_include
        for path in (".env", ".env.local", ".env.example", "env.example", "tests/test.env", "storage/ab12", ".git/config", "nyayavedika/__pycache__/x.pyc", "nyayavedika_dev.db",
                     "kb/a.txt", "dist/old.zip"):
            self.assertFalse(inc(path), path)
        for path in ("server.py", "nyayavedika/auth.py", "docs/EVAL.md"):
            self.assertTrue(inc(path), path)


@unittest.skipUnless(HAS_SERVER_DEPS, "fastapi / httpx / sqlalchemy / langgraph not installed")
class ServerRoleTests(unittest.TestCase):
    """End-to-end through FastAPI; runs where the full requirements are installed."""

    @classmethod
    def setUpClass(cls):
        from fastapi.testclient import TestClient
        from nyayavedika import db
        db.reset_engine_for_tests(f"sqlite:///{tempfile.mkdtemp()}/t.db")
        import server
        cls.client = TestClient(server.app)

    def setUp(self):
        self.old = (config.DEMO_TOKEN_STAFF, config.DEMO_TOKEN_LAWYER, config.DEMO_TOKEN_CITIZEN)
        _set_tokens()

    def tearDown(self):
        _set_tokens(*self.old)

    def h(self, role):
        return {"Authorization": f"Bearer {TOKENS[role]}"}

    def test_role_matrix_over_http(self):
        c = self.client
        self.assertEqual(c.get("/api/cases").status_code, 401)
        self.assertEqual(c.get("/api/cases", headers=self.h("staff")).status_code, 200)
        self.assertEqual(c.get("/api/cases", headers=self.h("citizen")).status_code, 403)
        self.assertEqual(c.post("/api/alerts/decide", json={}, headers=self.h("citizen")).status_code, 403)
        self.assertEqual(c.get("/api/alerts", headers=self.h("lawyer")).status_code, 200)
        self.assertEqual(c.get("/api/drafting/sections", headers=self.h("citizen")).status_code, 403)
        for path, body in (
            ("/api/advocate/workspaces", {}),
            ("/api/advocate/documents", {}),
            ("/api/advocate/documents/sample/preview", {}),
            ("/api/advocate/documents/sample/insights", {}),
            ("/api/advocate/documents/sample/chat", {}),
            ("/api/advocate/documents/sample/chat/prepare", {}),
            ("/api/advocate/studio", {}),
        ):
            self.assertEqual(c.post(path, json=body, headers=self.h("staff")).status_code, 403, path)
            self.assertEqual(c.post(path, json=body, headers=self.h("citizen")).status_code, 403, path)
        self.assertEqual(c.post("/api/legal-aid", json={"applicant": {"annual_income": 1}},
                                headers=self.h("citizen")).status_code, 200)
        self.assertEqual(c.get("/api/health").status_code, 200)

    def test_shared_demo_token_uses_portal_role_header(self):
        _set_tokens("mourya", "mourya", "mourya")
        for role in auth.ALL_ROLES:
            response = self.client.get("/api/whoami", headers={
                "Authorization": "Bearer mourya",
                "X-Demo-Role": role,
            })
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.json()["role"], role)

        lawyer = self.client.post(
            "/api/advocate/workspaces",
            headers={"Authorization": "Bearer mourya", "X-Demo-Role": "lawyer"},
            json={},
        )
        self.assertEqual(lawyer.status_code, 200, lawyer.text)

    def test_superintendent_letter_route_is_role_gated_and_returns_docx(self):
        from nyayavedika import store

        with store.connect() as db:
            store.prepare_database(db)
            alert_id = db.insert("alerts", [{
                "case_id": "UT/HTTP",
                "kind": "undertrial_release",
                "status": "pending",
                "created_at": datetime.now(timezone.utc).isoformat(),
                "details": {"custody_since": "2023-01-12", "release_check": {
                    "custody_days": 1383, "threshold_days": 851, "basis": "one-third (first-time offender)"}},
                "draft": "",
            }], returning="id")
            db.commit()

        self.assertEqual(
            self.client.get(f"/api/alerts/{alert_id}/superintendent.docx?language=te").status_code, 401)
        for language in ("hi", "te"):
            response = self.client.get(
                f"/api/alerts/{alert_id}/superintendent.docx?language={language}", headers=self.h("staff"))
            self.assertEqual(response.status_code, 200, response.text)
            self.assertEqual(response.headers["content-type"],
                             "application/vnd.openxmlformats-officedocument.wordprocessingml.document")
            self.assertIn(f"custody_record_review_request_UT_HTTP_{language}.docx",
                          response.headers["content-disposition"])
            self.assertTrue(response.content.startswith(b"PK"))

        self.assertEqual(self.client.get(
            f"/api/alerts/{alert_id}/superintendent.docx?language=en", headers=self.h("lawyer")).status_code, 403)

    def test_lawyers_only_see_and_decide_alerts_with_registry_assigned_counsel(self):
        from nyayavedika import store

        with store.connect() as db:
            store.prepare_database(db)
            unassigned_id = db.insert("alerts", [
                {"case_id": "UT/UNASSIGNED-GATE", "kind": "undertrial_release", "status": "pending",
                 "created_at": datetime.now(timezone.utc).isoformat(), "details": {}, "draft": "draft"},
            ], returning="id")
            assigned_id = db.insert("alerts", [
                {"case_id": "UT/ASSIGNED-GATE", "kind": "undertrial_release", "status": "pending",
                 "created_at": datetime.now(timezone.utc).isoformat(),
                 "details": {"counsel": {"name": "Advocate Example"}}, "draft": "draft"},
            ], returning="id")
            db.commit()

        lawyer_alerts = self.client.get("/api/alerts?status=all", headers=self.h("lawyer")).json()["alerts"]
        staff_alerts = self.client.get("/api/alerts?status=all", headers=self.h("staff")).json()["alerts"]
        self.assertNotIn(unassigned_id, [a["id"] for a in lawyer_alerts])
        self.assertIn(assigned_id, [a["id"] for a in lawyer_alerts])
        self.assertIn(unassigned_id, [a["id"] for a in staff_alerts])

        decision = self.client.post("/api/alerts/decide", headers=self.h("lawyer"),
                                    json={"decisions": {str(unassigned_id): {"approve": True}}})
        self.assertEqual(decision.status_code, 403, decision.text)
        draft = self.client.get(f"/api/alerts/{unassigned_id}/release.docx", headers=self.h("lawyer"))
        self.assertEqual(draft.status_code, 403, draft.text)
        approved = self.client.post("/api/alerts/decide", headers=self.h("lawyer"),
                                    json={"decisions": {str(assigned_id): {"approve": True}}})
        self.assertEqual(approved.status_code, 200, approved.text)

    def test_advocate_documents_are_workspace_scoped_and_hidden_from_staff_sources(self):
        import base64
        import server
        lawyer = self.client.post("/api/advocate/workspaces", headers=self.h("lawyer"))
        self.assertEqual(lawyer.status_code, 200)
        workspace = lawyer.json()["workspace_token"]
        second = self.client.post("/api/advocate/workspaces", headers=self.h("lawyer"))
        self.assertEqual(second.status_code, 200)

        with mock.patch.object(server.advocate.intake, "pdf_page_count", return_value=1), \
                mock.patch.object(server.advocate.ocr, "extract", return_value=[
                    {"page": 1, "text": "The applicant filed this petition on 1 January 2024.",
                     "source": "native", "confidence": None},
                ]):
            uploaded = self.client.post("/api/advocate/documents", headers=self.h("lawyer"), json={
                "workspace_token": workspace,
                "filename": "petition.pdf",
                "content_base64": base64.b64encode(b"%PDF-1.4 test").decode("ascii"),
            })
        self.assertEqual(uploaded.status_code, 200, uploaded.text)
        doc_id = uploaded.json()["doc_id"]
        self.assertEqual(self.client.get(
            f"/api/documents/{doc_id}/pages/1", headers=self.h("staff")
        ).status_code, 404)
        preview = self.client.post(
            f"/api/advocate/documents/{doc_id}/preview", headers=self.h("lawyer"),
            json={"workspace_token": workspace},
        )
        self.assertEqual(preview.status_code, 200, preview.text)
        self.assertEqual(preview.headers["content-type"], "application/pdf")
        self.assertEqual(preview.content, b"%PDF-1.4 test")
        unauthorized_preview = self.client.post(
            f"/api/advocate/documents/{doc_id}/preview", headers=self.h("lawyer"),
            json={"workspace_token": second.json()["workspace_token"]},
        )
        self.assertEqual(unauthorized_preview.status_code, 404)
        with mock.patch.object(server.advocate.llm, "available", return_value=True), \
                mock.patch.object(server.advocate.summarise, "call") as generate:
            response = self.client.post(
                f"/api/advocate/documents/{doc_id}/insights", headers=self.h("lawyer"),
                json={"workspace_token": second.json()["workspace_token"], "insight_type": "facts"},
            )
        self.assertEqual(response.status_code, 404)
        generate.assert_not_called()

    def test_advocate_chat_accepts_assistant_source_metadata_from_previous_turns(self):
        import server
        payload = {
            "workspace_token": "workspace-token",
            "messages": [
                {"role": "user", "content": "What happened?"},
                {"role": "assistant", "content": "A hearing was scheduled.",
                 "sources": [{"page": 2, "excerpt": "The matter was listed."}]},
                {"role": "user", "content": "When?"},
            ],
        }
        expected_messages = [
            {"role": "user", "content": "What happened?"},
            {"role": "assistant", "content": "A hearing was scheduled."},
            {"role": "user", "content": "When?"},
        ]
        with mock.patch.object(server.advocate, "chat_with_document",
                               return_value={"answer": "On 15 January [p. 2]."}) as chat:
            response = self.client.post(
                "/api/advocate/documents/document-id/chat", headers=self.h("lawyer"), json=payload
            )

        self.assertEqual(response.status_code, 200, response.text)
        chat.assert_called_once_with("workspace-token", "document-id", expected_messages)

    def test_legal_aid_question_limits_and_followup_count(self):
        import server
        session_id = f"test-session-{os.urandom(8).hex()}"
        with mock.patch.object(server.legal_aid, "answer_question", return_value={"answer": "Grounded answer."}):
            for used in range(1, server.legal_aid.MAX_FOLLOWUPS + 1):
                response = self.client.post("/api/legal-aid/ask", json={
                    "question": "What does this mean?", "question_session": session_id
                })
                self.assertEqual(response.status_code, 200)
                self.assertEqual(response.json()["followups_used"], used)
            limited = self.client.post("/api/legal-aid/ask", json={
                "question": "One more question?", "question_session": session_id
            })
        self.assertEqual(limited.status_code, 429)
        self.assertIn("5-question follow-up limit", limited.json()["detail"])

    def test_legal_aid_question_requires_session_id(self):
        response = self.client.post("/api/legal-aid/ask", json={"question": "What does this mean?"})
        self.assertEqual(response.status_code, 422)
        self.assertEqual(response.json()["detail"][0]["loc"], ["body", "question_session"])

    def test_legal_aid_question_caps_attachments_and_pages(self):
        import base64
        import server
        too_many = self.client.post("/api/legal-aid/ask", json={
            "question": "Question?", "question_session": f"test-{os.urandom(8).hex()}",
            "documents": [{"filename": "a.txt", "text": "a"}, {"filename": "b.txt", "text": "b"},
                          {"filename": "c.txt", "text": "c"}]
        })
        self.assertEqual(too_many.status_code, 413)
        self.assertIn("no more than 2 documents", too_many.json()["detail"])
        session_id = f"test-{os.urandom(8).hex()}"
        with mock.patch.object(server.ocr, "extract", return_value=[
            {"page": number, "text": "page", "source": "native"} for number in range(1, 52)
        ]):
            too_many_pages = self.client.post("/api/documents/summarize", json={
                "filename": "large.pdf", "content_base64": base64.b64encode(b"%PDF").decode()
            })
        self.assertEqual(too_many_pages.status_code, 413)
        self.assertIn("50-page-per-file", too_many_pages.json()["detail"])
        with mock.patch.object(server.intake, "pdf_page_count", return_value=51):
            analyzed_too_many_pages = self.client.post("/api/documents/analyze", json={
                "filename": "large.pdf", "content_base64": base64.b64encode(b"%PDF").decode()
            }, headers=self.h("staff"))
        self.assertEqual(analyzed_too_many_pages.status_code, 413)
        self.assertIn("50-page-per-file", analyzed_too_many_pages.json()["detail"])

    def test_citizen_cannot_resume_staff_thread(self):
        r = self.client.post("/api/agent/resume", json={"thread_id": "staff-abc", "answer": "x"}, headers=self.h("citizen"))
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
