import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import types
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pydantic import BaseModel  # noqa: E402
from nyayavedika import config, llm  # noqa: E402


class Reply(BaseModel):
    value: str


class WorkingAzure:
    instances = []

    def __init__(self):
        self.calls = []
        type(self).instances.append(self)

    def text(self, *args, **kwargs):
        self.calls.append(("text", args, kwargs))
        return "Azure response"

    def structured(self, *args, **kwargs):
        self.calls.append(("structured", args, kwargs))
        return {"value": "Azure structured response"}


class AzureOnlyTests(unittest.TestCase):
    def setUp(self):
        self.old = (config.AZURE_OPENAI_API_KEY, config.AZURE_OPENAI_ENDPOINT, config.AZURE_OPENAI_DEPLOYMENT,
                    config.AZURE_OPENAI_FAST_DEPLOYMENT, config.FORCE_OFFLINE, config.LLM_REASONING_EFFORT,
                    llm.AzureOpenAIBackend._effort_rejected)
        config.AZURE_OPENAI_API_KEY = "configured"
        config.AZURE_OPENAI_ENDPOINT = "https://example.invalid/"
        config.AZURE_OPENAI_DEPLOYMENT = "main-deployment"
        config.AZURE_OPENAI_FAST_DEPLOYMENT = ""
        config.FORCE_OFFLINE = False
        WorkingAzure.instances = []
        llm.set_backend(None)

    def tearDown(self):
        llm.set_backend(None)
        (config.AZURE_OPENAI_API_KEY, config.AZURE_OPENAI_ENDPOINT, config.AZURE_OPENAI_DEPLOYMENT,
         config.AZURE_OPENAI_FAST_DEPLOYMENT, config.FORCE_OFFLINE, config.LLM_REASONING_EFFORT,
         llm.AzureOpenAIBackend._effort_rejected) = self.old

    def test_calls_go_to_azure_and_status_names_the_deployments(self):
        with mock.patch.object(llm, "AzureOpenAIBackend", WorkingAzure):
            self.assertEqual(llm.chat("system", [{"role": "user", "content": "hello"}]), "Azure response")
            self.assertEqual(llm.structured("system", "hello", Reply).value, "Azure structured response")
            self.assertEqual(len(WorkingAzure.instances), 1)
            self.assertEqual([c[0] for c in WorkingAzure.instances[0].calls], ["text", "structured"])
            st = llm.status()
            self.assertEqual((st["provider"], st["model"], st["fast_model"]),
                             ("azure_openai", "main-deployment", "main-deployment"))

    def test_fast_calls_use_the_fast_deployment_when_set(self):
        config.AZURE_OPENAI_FAST_DEPLOYMENT = "fast-deployment"
        with mock.patch.object(llm, "AzureOpenAIBackend", WorkingAzure):
            llm.chat("system", [{"role": "user", "content": "a"}], fast=True)
            llm.chat("system", [{"role": "user", "content": "b"}])
            models = [c[1][0] for c in WorkingAzure.instances[0].calls]
            self.assertEqual(models, ["fast-deployment", "main-deployment"])

    def test_missing_settings_disable_the_llm_with_a_reason(self):
        config.AZURE_OPENAI_API_KEY = None
        self.assertFalse(llm.available())
        self.assertIn("AZURE_OPENAI_API_KEY", llm.status()["reason"])

    def test_a_failing_call_is_raised_not_sent_to_another_provider(self):
        class Failing(WorkingAzure):
            def text(self, *a, **k):
                raise RuntimeError("azure failed")
        llm.set_backend(Failing())
        with self.assertRaisesRegex(RuntimeError, "azure failed"):
            llm.chat("system", [{"role": "user", "content": "hello"}])

    def test_azure_backend_uses_configured_endpoint_version_and_deployment(self):
        response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="Azure response"))])
        client = mock.Mock()
        client.chat.completions.create.return_value = response
        azure_client = mock.Mock(return_value=client)
        openai_module = types.ModuleType("openai")
        openai_module.AzureOpenAI = azure_client

        with mock.patch.dict(sys.modules, {"openai": openai_module}):
            backend = llm.AzureOpenAIBackend()
            result = backend.text("main-deployment", "system", [{"role": "user", "content": "hello"}])

        self.assertEqual(result, "Azure response")
        azure_client.assert_called_once_with(
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            timeout=config.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=config.LLM_CLIENT_MAX_RETRIES,
        )
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], "main-deployment")

    def test_reasoning_effort_rejected_by_the_deployment_is_dropped_and_remembered(self):
        config.LLM_REASONING_EFFORT = "minimal"
        llm.AzureOpenAIBackend._effort_rejected = False
        error = RuntimeError("Unrecognized request argument supplied: reasoning_effort")
        error.status_code = 400
        response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content="ok"))])
        client = mock.Mock()
        client.chat.completions.create.side_effect = [error, response, response]
        backend = object.__new__(llm.AzureOpenAIBackend)
        backend._client = client

        self.assertEqual(backend.text("m", "system", [{"role": "user", "content": "hi"}]), "ok")
        self.assertEqual(backend.text("m", "system", [{"role": "user", "content": "again"}]), "ok")
        calls = client.chat.completions.create.call_args_list
        self.assertIn("reasoning_effort", calls[0].kwargs)
        self.assertNotIn("reasoning_effort", calls[1].kwargs)
        self.assertNotIn("reasoning_effort", calls[2].kwargs)  # remembered: no second failing round trip

    def test_azure_empty_json_schema_response_does_not_retry_in_json_object_mode(self):
        response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(
                message=types.SimpleNamespace(content="", refusal=None),
                finish_reason="length",
            )]
        )
        client = mock.Mock()
        client.chat.completions.create.return_value = response
        backend = object.__new__(llm.AzureOpenAIBackend)
        backend._client = client

        with self.assertRaisesRegex(ValueError, "empty structured response.*finish_reason='length'"):
            backend.structured("model", "system", [{"role": "user", "content": "text"}], Reply)

        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_azure_retries_json_object_when_json_schema_request_is_rejected(self):
        error = RuntimeError("response format unsupported")
        error.status_code = 400
        response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"value": "ok"}'))]
        )
        client = mock.Mock()
        client.chat.completions.create.side_effect = [error, response]
        backend = object.__new__(llm.AzureOpenAIBackend)
        backend._client = client

        result = backend.structured("model", "system", [{"role": "user", "content": "text"}], Reply)

        self.assertEqual(result.value, "ok")
        self.assertEqual(client.chat.completions.create.call_count, 2)
        self.assertEqual(
            client.chat.completions.create.call_args.kwargs["response_format"],
            {"type": "json_object"},
        )

    def test_azure_connection_error_does_not_retry_in_json_object_mode(self):
        error = RuntimeError("connection error")
        response = types.SimpleNamespace(
            choices=[types.SimpleNamespace(message=types.SimpleNamespace(content='{"value": "ok"}'))]
        )
        client = mock.Mock()
        client.chat.completions.create.side_effect = [error, response]
        backend = object.__new__(llm.AzureOpenAIBackend)
        backend._client = client

        with self.assertRaisesRegex(RuntimeError, "connection error"):
            backend.structured("model", "system", [{"role": "user", "content": "text"}], Reply)

        self.assertEqual(client.chat.completions.create.call_count, 1)

    def test_unrelated_bad_request_does_not_retry_as_json_object(self):
        error = RuntimeError("deployment is unavailable")
        error.status_code = 400
        client = mock.Mock()
        client.chat.completions.create.side_effect = error
        backend = object.__new__(llm.AzureOpenAIBackend)
        backend._client = client

        with self.assertRaisesRegex(RuntimeError, "deployment is unavailable"):
            backend.structured("model", "system", [{"role": "user", "content": "text"}], Reply)

        self.assertEqual(client.chat.completions.create.call_count, 1)


if __name__ == "__main__":
    unittest.main()
