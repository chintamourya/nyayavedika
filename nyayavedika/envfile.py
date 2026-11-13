"""The single settings source: the .env file in the repo root.

Rules:
  * Every setting is read from .env and ONLY from .env. Nothing is read from os.environ, and there are no defaults
    in code. A key missing from the file stops start-up with one error that lists every missing key.
  * An empty value is allowed (e.g. an optional API key); an absent key is not.
  * The file is always <repo root>/.env (in Docker: /app/.env, mounted at run time, never baked into the image).
    The checked-in .env.example is a placeholder template; it is not loaded by the application.
    There is no redirect variable or other runtime settings file.
Values are never printed or logged; loaded_from() reports the path only.
"""
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
_values: Dict[str, str] = {}
_missing: List[str] = []
_bad: List[str] = []
_source: Optional[Path] = None

# Test hook. Always EMPTY in a real run; only tests/_testenv.py fills it (to force offline mode and a throw-away
# database) so a test run can never touch live keys or the live database. Applied on top of what .env says.
OVERRIDES: Dict[str, str] = {}


class ConfigError(RuntimeError):
    pass


def default_path() -> Path:
    return ROOT / ".env"


def _unquote(value: str) -> str:
    v = value.strip()
    if len(v) >= 2 and v[0] == v[-1] and v[0] in "\"'":
        return v[1:-1]
    if " #" in v:  # inline comment after an unquoted value
        v = v.split(" #", 1)[0].rstrip()
    return v


def parse(text: str) -> Dict[str, str]:
    """KEY=VALUE lines; blank lines and # comments ignored; optional `export ` prefix; quotes stripped.
    A repeated key keeps its LAST value."""
    out: Dict[str, str] = {}
    for raw in text.splitlines():
        line = raw.strip().lstrip("\ufeff")
        if not line or line.startswith("#") or "=" not in line:
            continue
        if line.startswith("export "):
            line = line[len("export "):].lstrip()
        key, value = line.split("=", 1)
        key = key.strip()
        if key:
            out[key] = _unquote(value)
    return out


def load(path: Optional[Path] = None) -> Path:
    """Read .env into memory (os.environ is not touched). Raises ConfigError when the file is absent."""
    global _source, _values
    path = Path(path) if path else default_path()
    if not path.is_file():
        raise ConfigError(f"Settings file not found: {path}. Create a .env file in the project root "
                          f"(in Docker, mount it at /app/.env). Every key is listed in nyayavedika/config.py.")
    _values = {**parse(path.read_text(encoding="utf-8", errors="replace")), **OVERRIDES}
    _source = path
    _missing.clear()
    _bad.clear()
    return path


def loaded_from() -> Optional[Path]:
    return _source


# ---- typed readers: each returns a harmless placeholder on a problem and records it for check() ------------------
def _raw(key: str) -> Optional[str]:
    if key not in _values:
        if key not in _missing:
            _missing.append(key)
        return None
    return _values[key]


def string(key: str) -> str:
    v = _raw(key)
    return "" if v is None else v


def integer(key: str) -> int:
    v = _raw(key)
    try:
        return int(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        if v is not None:
            _bad.append(f"{key} must be a whole number, got {v!r}")
        return 0


def number(key: str) -> float:
    v = _raw(key)
    try:
        return float(v)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        if v is not None:
            _bad.append(f"{key} must be a number, got {v!r}")
        return 0.0


def boolean(key: str) -> bool:
    v = _raw(key)
    if v is None:
        return False
    if v.strip().lower() in ("1", "true", "yes", "on"):
        return True
    if v.strip().lower() in ("0", "false", "no", "off", ""):
        return False
    _bad.append(f"{key} must be true/false (or 1/0), got {v!r}")
    return False


def items(key: str) -> List[str]:
    """Comma-separated list; empty entries dropped."""
    v = _raw(key)
    return [p.strip() for p in (v or "").split(",") if p.strip()]


def json_value(key: str) -> Any:
    v = _raw(key)
    if v is None:
        return None
    try:
        return json.loads(v)
    except ValueError:
        _bad.append(f"{key} must be valid JSON, got {v!r}")
        return None


def check() -> None:
    """Call once after every setting has been read: one error naming everything wrong."""
    problems = []
    if _missing:
        problems.append("missing from the settings file: " + ", ".join(_missing))
    problems += _bad
    if problems:
        raise ConfigError(f"Invalid settings in {_source} (every key is listed in nyayavedika/config.py):\n  - " + "\n  - ".join(problems))
