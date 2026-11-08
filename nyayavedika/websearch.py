"""Tavily web search, restricted to official Indian legal/government domains by default.

Used by agents for facts that change and are not in the knowledge base: the current State income
limit for legal aid, DLSA addresses and helplines, recent amendments, Lok Adalat dates.
"""
import logging
from typing import Dict, List, Optional

from . import config
from .documents import redact_pii

logger = logging.getLogger(__name__)
_client = None
_disabled_reason: Optional[str] = None


def _get_client():
    global _client, _disabled_reason
    if _client is not None or _disabled_reason:
        return _client
    if not config.TAVILY_API_KEY:
        _disabled_reason = "TAVILY_API_KEY not set"
    else:
        try:
            from tavily import TavilyClient
            _client = TavilyClient(api_key=config.TAVILY_API_KEY)
        except ImportError:
            _disabled_reason = "tavily-python not installed"
    return _client


def available() -> bool:
    return _get_client() is not None


SEARCH_TIMEOUT_SECONDS = 15   # the SDK default is ~60 s; a stuck search should fail fast and say so


def search(query: str, max_results: int = config.WEBSEARCH_MAX_RESULTS, trusted_only: bool = True, topic: str = "general",
           include_answer: bool = True) -> Dict:
    """include_answer=False skips Tavily's own generated summary (an extra model pass on their side) for callers that
    only read the result list, such as the citizen legal-problem research."""
    query = redact_pii(query)   # queries leave the system: mask phone / email / Aadhaar / PAN / card numbers first
    client = _get_client()
    if client is None:
        return {"answer": None, "results": [], "error": _disabled_reason}
    kwargs = dict(search_depth=config.TAVILY_SEARCH_DEPTH, max_results=max_results, include_answer=include_answer, topic=topic)
    if trusted_only:
        kwargs["include_domains"] = config.TRUSTED_DOMAINS
    try:
        try:
            res = client.search(query, timeout=SEARCH_TIMEOUT_SECONDS, **kwargs)
        except TypeError:   # an older tavily-python without the timeout argument
            res = client.search(query, **kwargs)
    except Exception as exc:
        logger.warning("Tavily search failed: %s", exc)
        return {"answer": None, "results": [], "error": str(exc)}
    results: List[Dict] = [{"title": r.get("title"), "url": r.get("url"), "content": (r.get("content") or "")[:config.WEBSEARCH_CONTENT_CHARS],
                            "score": r.get("score")} for r in res.get("results", [])]
    return {"answer": res.get("answer"), "results": results}
