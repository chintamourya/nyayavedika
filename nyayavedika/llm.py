"""LLM client: Azure OpenAI only, with a pluggable backend.

Lineage: consolidates provider wrappers from backend-case-search-prod/llm/llm.py
and casechat-backend/source/llm_v2.py behind one shared client. Every call masks PII first.
Tests swap in a scripted backend with `set_backend()`, so agent graphs run without network.
"""
import json
import logging
import re
from typing import List, Optional, Type, TypeVar

from pydantic import BaseModel, Field

from . import config
from .documents import redact_pii

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)

PROVIDER = "azure_openai"


class LLMUnavailable(RuntimeError):
    pass


class LanguageRewrite(BaseModel):
    translations: List[str] = Field(default_factory=list)


class AzureOpenAIBackend:
    """Azure OpenAI Chat Completions. `model` is the Azure *deployment* name (main or fast deployment)."""

    _effort_rejected = False  # set once when the deployment does not accept `reasoning_effort` (non-reasoning models)

    def __init__(self):
        from openai import AzureOpenAI  # imported lazily so the app starts without the SDK
        # one SDK retry only: long stacked 429 back-offs froze the chat and the intake rows
        self._client = AzureOpenAI(
            api_version=config.AZURE_OPENAI_API_VERSION,
            azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
            api_key=config.AZURE_OPENAI_API_KEY,
            timeout=config.LLM_REQUEST_TIMEOUT_SECONDS,
            max_retries=config.LLM_CLIENT_MAX_RETRIES,
        )

    @staticmethod
    def _msgs(system_prompt: str, messages: List[dict]) -> List[dict]:
        out = [{"role": "system", "content": system_prompt}]
        for m in messages:  # earlier assistant turns keep their role, so the model sees a real conversation
            out.append({"role": "assistant" if m["role"] == "assistant" else "user", "content": m["content"]})
        return out

    @staticmethod
    def _deployment(model: Optional[str]) -> str:
        return model or config.AZURE_OPENAI_DEPLOYMENT

    def _create(self, **kwargs):
        """chat.completions.create with `reasoning_effort` (the main speed lever on reasoning deployments such as
        gpt-5-mini / o-series). A deployment that rejects the parameter is retried once without it, then remembered."""
        effort = config.LLM_REASONING_EFFORT
        if effort and not AzureOpenAIBackend._effort_rejected:
            try:
                return self._client.chat.completions.create(reasoning_effort=effort, **kwargs)
            except Exception as exc:
                if getattr(exc, "status_code", None) == 400 and "reasoning_effort" in str(exc).lower():
                    logger.warning("deployment does not accept reasoning_effort (%s); calling without it", exc)
                    AzureOpenAIBackend._effort_rejected = True
                else:
                    raise
        return self._client.chat.completions.create(**kwargs)

    def text(self, model: str, system_prompt: str, messages: List[dict]) -> str:
        r = self._create(model=self._deployment(model), messages=self._msgs(system_prompt, messages),
                         max_completion_tokens=config.LLM_MAX_COMPLETION_TOKENS)
        return r.choices[0].message.content or ""

    def structured(self, model: str, system_prompt: str, messages: List[dict], schema: Type[T],
                   max_tokens: Optional[int] = None) -> T:
        msgs = self._msgs(system_prompt, messages)
        options = {"model": self._deployment(model), "max_completion_tokens": max_tokens or config.LLM_MAX_COMPLETION_TOKENS}
        try:
            r = self._create(
                messages=msgs,
                response_format={"type": "json_schema", "json_schema": {
                    "name": schema.__name__, "schema": schema.model_json_schema(), "strict": False}},
                **options,
            )
        except Exception as exc:
            message = str(exc).casefold()
            format_rejected = (
                getattr(exc, "status_code", None) == 400
                and any(term in message for term in ("response_format", "response format", "json_schema", "json schema"))
                and any(term in message for term in ("unsupported", "not supported", "invalid"))
            )
            if not format_rejected:
                raise
            logger.warning("Azure OpenAI json_schema format is unsupported (%s); retrying in json_object mode",
                           type(exc).__name__)
            msgs[0]["content"] += ("\n\nReply with ONLY a JSON object matching this JSON Schema:\n"
                                   + json.dumps(schema.model_json_schema()))
            r = self._create(messages=msgs, response_format={"type": "json_object"}, **options)
            return schema.model_validate(extract_and_parse_json(r.choices[0].message.content))
        choice = r.choices[0]
        content = choice.message.content
        if not content or not content.strip():
            raise ValueError(
                "Azure OpenAI returned an empty structured response "
                f"(finish_reason={getattr(choice, 'finish_reason', None)!r})"
            )
        return schema.model_validate_json(content)


def _models():
    """(main, fast) Azure deployment names; the fast one falls back to the main deployment."""
    return config.AZURE_OPENAI_DEPLOYMENT, config.AZURE_OPENAI_FAST_DEPLOYMENT or config.AZURE_OPENAI_DEPLOYMENT


_backend = None
_disabled_reason: Optional[str] = None


def set_backend(backend) -> None:
    """Inject a backend (tests / alternative providers). Pass None to reset."""
    global _backend, _disabled_reason
    _backend, _disabled_reason = backend, None


def _get_backend():
    global _backend, _disabled_reason
    if _backend is not None or _disabled_reason:
        return _backend
    if config.FORCE_OFFLINE:
        _disabled_reason = "offline mode (NYAYAVEDIKA_OFFLINE=1)"
    else:
        missing = [k for k, v in (("AZURE_OPENAI_API_KEY", config.AZURE_OPENAI_API_KEY),
                                  ("AZURE_OPENAI_ENDPOINT", config.AZURE_OPENAI_ENDPOINT),
                                  ("AZURE_OPENAI_DEPLOYMENT", config.AZURE_OPENAI_DEPLOYMENT)) if not v]
        if missing:
            _disabled_reason = f"{', '.join(missing)} not set"
        else:
            try:
                _backend = AzureOpenAIBackend()
            except ImportError:
                _disabled_reason = "openai SDK not installed"
            except Exception as exc:
                _disabled_reason = f"Azure OpenAI client unavailable: {exc}"
    if _disabled_reason:
        logger.info("LLM disabled - %s", _disabled_reason)
    return _backend


def available() -> bool:
    return _get_backend() is not None


def status() -> dict:
    _get_backend()
    model, fast_model = _models()
    return {"llm_enabled": _backend is not None, "provider": PROVIDER, "model": model, "fast_model": fast_model,
            "reason": _disabled_reason or "ok", "pii_redaction": config.REDACT_BEFORE_LLM}


def _prep(messages: List[dict]) -> List[dict]:
    if not config.REDACT_BEFORE_LLM:
        return messages
    return [{**m, "content": redact_pii(m["content"])} for m in messages]


def _require():
    backend = _get_backend()
    if backend is None:
        raise LLMUnavailable(_disabled_reason or "LLM unavailable")
    return backend


def _invoke(method: str, *args, **kwargs):
    return getattr(_require(), method)(*args, **kwargs)


def text(system_prompt: str, user_prompt: str, fast: bool = False) -> str:
    return chat(system_prompt, [{"role": "user", "content": user_prompt}], fast=fast)


def chat(system_prompt: str, messages: List[dict], fast: bool = False) -> str:
    model = _models()[1] if fast else _models()[0]
    return _invoke("text", model, system_prompt, _prep(messages))


def structured(system_prompt: str, user_prompt: str, schema: Type[T], fast: bool = False,
               max_tokens: Optional[int] = None) -> T:
    return structured_chat(system_prompt, [{"role": "user", "content": user_prompt}], schema, fast=fast, max_tokens=max_tokens)


def structured_chat(system_prompt: str, messages: List[dict], schema: Type[T], fast: bool = False,
                    max_tokens: Optional[int] = None) -> T:
    model = _models()[1] if fast else _models()[0]
    if max_tokens:
        try:
            result = _invoke("structured", model, system_prompt, _prep(messages), schema, max_tokens=max_tokens)
        except TypeError:  # a backend without an output cap (test doubles)
            result = _invoke("structured", model, system_prompt, _prep(messages), schema)
    else:
        result = _invoke("structured", model, system_prompt, _prep(messages), schema)
    if isinstance(result, dict):  # scripted test backends may return plain dicts
        result = schema.model_validate(result)
    return result


def enforce_language(texts: List[str], language: str) -> List[str]:
    """Rewrite visible response text in the selected language; retain the original if rewriting fails."""
    originals = [str(text or "") for text in texts]
    target = {"english": "English", "hindi": "Hindi", "telugu": "Telugu"}.get((language or "").strip().casefold())
    if not target or not any(text.strip() for text in originals) or not available():
        return originals

    script = {"Hindi": re.compile(r"[\u0900-\u097f]"),
              "Telugu": re.compile(r"[\u0c00-\u0c7f]")}.get(target)
    if target == "English" and not any(re.search(r"[\u0900-\u097f\u0c00-\u0c7f]", text) for text in originals):
        return originals

    prompt = (
        f"Rewrite every supplied text exclusively in {target}. The user's selected language is authoritative, "
        "regardless of the language in which the user wrote. Do not code-switch, include a bilingual version, or "
        "leave English sentences untranslated. Use the normal script for the selected language. Preserve meaning, "
        "tone, list order, legal citations, section numbers, case numbers, URLs, phone numbers, and official names "
        "or abbreviations when translating them would make them harder to identify. Return exactly one translation "
        "for each input string, in the same order, with no commentary."
    )
    try:
        result = structured(prompt, json.dumps(originals, ensure_ascii=False), LanguageRewrite,
                           fast=True, max_tokens=config.LLM_MAX_COMPLETION_TOKENS)
        translated = [text.strip() for text in result.translations]
        if len(translated) != len(originals) or any(
                source.strip() and not output for source, output in zip(originals, translated)):
            raise ValueError("language rewrite returned an incomplete translation")
        for source, output in zip(originals, translated):
            if re.findall(r"\d+(?:[./-]\d+)*", source) != re.findall(r"\d+(?:[./-]\d+)*", output):
                raise ValueError("language rewrite changed a number or citation")
            if re.findall(r"https?://\S+|www\.\S+", source) != re.findall(r"https?://\S+|www\.\S+", output):
                raise ValueError("language rewrite changed a URL")
        if script:
            letters = [char for text in translated for char in text if char.isalpha()]
            target_letters = sum(bool(script.fullmatch(char)) for char in letters)
            if letters and target_letters / len(letters) < 0.7:
                raise ValueError("language rewrite did not use the selected language consistently")
        elif any(re.search(r"[\u0900-\u097f\u0c00-\u0c7f]", text) for text in translated):
            raise ValueError("English rewrite retained non-English script")
        return translated
    except Exception as exc:
        logger.warning("Selected-language rewrite failed (%s); keeping the original response", type(exc).__name__)
        return originals


def extract_and_parse_json(llm_response: str):
    """Pull the first JSON object/array out of free text (adapted from casechat llm_v2.py)."""
    s = llm_response.strip()
    if s.startswith("```"):
        s = s.split("```")[1]
        if s.startswith("json"):
            s = s[4:]
    starts = [i for i in (s.find("{"), s.find("[")) if i != -1]
    if not starts:
        raise ValueError("No JSON found in response")
    return json.loads(s[min(starts):max(s.rfind("}"), s.rfind("]")) + 1])
