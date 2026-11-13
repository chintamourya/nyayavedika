import os
import sys; sys.path.insert(0, os.path.dirname(os.path.abspath(__file__))); import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)
import sys
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


class FailingGroq:
    calls = 0

    def __init__(self):
        pass

    def text(self, *args, **kwargs):
        type(self).calls += 1
        raise RuntimeError("primary provider failed")


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


class LLMFallbackTests(unittest.TestCase):
    def setUp(self):
        self.old = (config.AZURE_OPENAI_API_KEY, config.FORCE_OFFLINE, config.AZURE_OPENAI_ENDPOINT)
        config.AZURE_OPENAI_API_KEY = "configured"
        config.AZURE_OPENAI_ENDPOINT = "https://example.invalid/"
        config.FORCE_OFFLINE = False
        WorkingAzure.instances = []
        llm.set_backend(None)

    def tearDown(self):
        llm.set_backend(None)
        config.AZURE_OPENAI_API_KEY, config.FORCE_OFFLINE, config.AZURE_OPENAI_ENDPOINT = self.old

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
            result = backend.text("", "system", [{"role": "user", "content": "hello"}])

        self.assertEqual(result, "Azure response")
        azure_client.assert_called_once_with(
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            timeout=90,
            max_retries=1,
        )
        self.assertEqual(client.chat.completions.create.call_args.kwargs["model"], config.AZURE_OPENAI_DEPLOYMENT)

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


if __name__ == "__main__":
    unittest.main()
