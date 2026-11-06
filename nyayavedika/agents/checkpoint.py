"""LangGraph checkpointer factory.

"postgres" (default) - PostgresSaver on a psycopg connection pool: paused conversations and pending
                       human approvals (release applications, cause lists) survive restarts and are
                       shared across workers. psycopg / psycopg_pool are LGPL-3.0 (approved).
"memory"             - InMemorySaver, for tests and quick local runs without Postgres.

The checkpoint DSN is CHECKPOINT_DB_URI, or derived from DATABASE_URL when that points at Postgres.
"""
import logging

from .. import config

logger = logging.getLogger(__name__)
_saver = None
_pool = None


def checkpoint_dsn() -> str:
    if config.CHECKPOINT_DB_URI:
        return config.CHECKPOINT_DB_URI
    url = config.DATABASE_URL
    if url.startswith("postgresql"):
        # SQLAlchemy URL (postgresql+pg8000://...) -> libpq URI (postgresql://...)
        dsn = "postgresql://" + url.split("://", 1)[1]
        host = dsn.split("@")[-1].split("/")[0].split(":")[0]
        if host not in config.DATABASE_LOCAL_HOSTS and "sslmode=" not in dsn:
            dsn += ("&" if "?" in dsn else "?") + "sslmode=require"   # hosted Postgres (Supabase) needs TLS
        return dsn
    return ""


def get_checkpointer():
    global _saver, _pool
    if _saver is not None:
        return _saver
    dsn = checkpoint_dsn() if config.CHECKPOINTER == "postgres" else ""
    if dsn:
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
            from psycopg.rows import dict_row
            from psycopg_pool import ConnectionPool
            _pool = ConnectionPool(conninfo=dsn, min_size=1, max_size=config.CHECKPOINT_POOL_SIZE, open=False, timeout=config.CHECKPOINT_POOL_TIMEOUT_SECONDS,
                                   kwargs={"autocommit": True, "prepare_threshold": 0, "row_factory": dict_row,
                                           "connect_timeout": config.CHECKPOINT_CONNECT_TIMEOUT_SECONDS})
            _pool.open(wait=True, timeout=config.CHECKPOINT_POOL_TIMEOUT_SECONDS)   # fail fast with the real reason instead of retrying silently
            _saver = PostgresSaver(_pool)
            _saver.setup()  # idempotent: creates/migrates checkpoint tables
            logger.info("LangGraph checkpoints in Postgres (pool size %d)", config.CHECKPOINT_POOL_SIZE)
            return _saver
        except Exception as exc:
            logger.error("Postgres checkpointer failed (%s: %s) - falling back to in-memory checkpoints; "
                         "paused threads will not survive a restart", type(exc).__name__, exc)
            if _pool is not None:
                try:
                    _pool.close()
                except Exception:
                    pass
            _pool = None
            from langgraph.checkpoint.memory import InMemorySaver
            _saver = InMemorySaver()
            return _saver
    else:
        if config.CHECKPOINTER == "postgres":
            logger.warning("NYAYAVEDIKA_CHECKPOINTER=postgres but no Postgres DSN (DATABASE_URL is %s) - "
                           "using in-memory checkpoints; paused threads will not survive a restart",
                           config.DATABASE_URL.split("://")[0])
        from langgraph.checkpoint.memory import InMemorySaver
        _saver = InMemorySaver()
    return _saver


def _reset_graph_caches() -> None:
    """Compiled graphs keep the checkpointer they were built with: drop them with it."""
    import sys
    for name in ("assistants", "document_analyst", "registry", "undertrial_watch"):
        mod = sys.modules.get(f"nyayavedika.agents.{name}")
        if mod is None:
            continue
        if hasattr(mod, "_agents"):
            mod._agents.clear()
        if hasattr(mod, "_graph"):
            mod._graph = None


def close() -> None:
    """Release pooled connections on shutdown."""
    global _saver, _pool
    if _pool is not None:
        try:
            _pool.close()
        except Exception as exc:  # shutting down anyway
            logger.warning("closing the checkpoint pool failed: %s", exc)
    _saver, _pool = None, None
    _reset_graph_caches()