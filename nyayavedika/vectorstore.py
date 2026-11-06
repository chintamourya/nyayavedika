"""Pinecone vector store with integrated (hosted) embeddings - no local embedding model needed.

Namespaces: `law` (bare acts, NALSA schemes), `judgments` (precedents), `casefiles` (uploads,
filtered by case_id). Records carry `chunk_text` (embedded) plus metadata for citations.
"""
import logging
from typing import Dict, List, Optional

from . import config
from .documents import redact_pii

logger = logging.getLogger(__name__)
_index = None
_disabled_reason: Optional[str] = None
UPSERT_BATCH = config.PINECONE_UPSERT_BATCH


_other: Dict[str, object] = {}  # extra indexes by name (e.g. PINECONE_LEGALAID_INDEX)


def _open(name: str):
    from pinecone import Pinecone
    pc = Pinecone(api_key=config.PINECONE_API_KEY)
    if not pc.has_index(name):
        pc.create_index_for_model(
            name=name, cloud=config.PINECONE_CLOUD, region=config.PINECONE_REGION,
            embed={"model": config.PINECONE_EMBED_MODEL, "field_map": {"text": "chunk_text"}},
        )
    return pc.Index(name)


def _get_index(name: Optional[str] = None):
    """The default index, or another named one (created on first use with the same embedding model)."""
    global _index, _disabled_reason
    if name and name != config.PINECONE_INDEX:
        if name not in _other and _get_index() is not None:
            try:
                _other[name] = _open(name)
            except Exception as exc:
                logger.warning("Pinecone index %s unavailable: %s", name, exc)
                return None
        return _other.get(name)
    if _index is not None or _disabled_reason:
        return _index
    if not config.PINECONE_API_KEY:
        _disabled_reason = "PINECONE_API_KEY not set"
        return None
    try:
        _index = _open(config.PINECONE_INDEX)
    except ImportError:
        _disabled_reason = "pinecone package not installed"
    except Exception as exc:
        _disabled_reason = f"Pinecone unavailable: {exc}"
    if _disabled_reason:
        logger.info("Vector store disabled - %s", _disabled_reason)
    return _index


def available() -> bool:
    return _get_index() is not None


def status() -> Dict:
    _get_index()
    return {"vector_db": _index is not None, "index": config.PINECONE_INDEX, "reason": _disabled_reason or "ok"}


def upsert_chunks(namespace: str, chunks: List[Dict], index_name: Optional[str] = None) -> int:
    """chunks: [{"id", "text", **metadata}] - metadata values must be str/number/bool/list[str]."""
    index = _get_index(index_name) if index_name else _get_index()
    if index is None:
        return 0
    records = []
    for c in chunks:
        meta = {k: v for k, v in c.items() if k not in ("id", "text") and v is not None}
        # Mask Aadhaar / phone / PAN / email before anything leaves for the index (not only before LLM calls).
        records.append({"_id": str(c["id"]), "chunk_text": redact_pii(c["text"][:config.PINECONE_MAX_CHUNK_CHARS]), **meta})
    for i in range(0, len(records), UPSERT_BATCH):
        index.upsert_records(namespace=namespace, records=records[i:i + UPSERT_BATCH])
    return len(records)


def search(namespace: str, query: str, top_k: int = 5, filter: Optional[Dict] = None,
           index_name: Optional[str] = None) -> List[Dict]:
    """Return [{"id", "score", "text", **metadata}] - empty list when Pinecone is not configured."""
    index = _get_index(index_name) if index_name else _get_index()
    if index is None:
        return []
    q = {"inputs": {"text": query}, "top_k": top_k}
    if filter:
        q["filter"] = filter
    res = index.search(namespace=namespace, query=q)
    hits = res["result"]["hits"] if isinstance(res, dict) else res.result.hits
    out = []
    for h in hits:
        h = h if isinstance(h, dict) else (h.to_dict() if hasattr(h, "to_dict") else dict(h))
        fields = dict(h.get("fields", {}))
        out.append({"id": h["_id"], "score": round(h["_score"], 4), "text": fields.pop("chunk_text", ""), **fields})
    return out
