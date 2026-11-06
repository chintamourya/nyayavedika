"""Settings: .env is the only source; nothing is read from the shell environment; a missing key is an error;
and no other file in the project carries settings."""
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(Path(__file__).resolve().parent))
import _testenv  # noqa: E402,F401  (offline settings, see tests/_testenv.py)

from nyayavedika import envfile  # noqa: E402


def _config_keys():
    return set(re.findall(r'\b[SIFBLJ]\("([A-Z0-9_]+)"\)', (ROOT / "nyayavedika" / "config.py").read_text()))


class EnvFileTests(unittest.TestCase):
    def test_parse(self):
        got = envfile.parse('# c\n\nA=1\nexport B = "two words"\nC=\'x#y\'\nD=plain # note\nnot a line\nA=2\n')
        self.assertEqual(got, {"A": "2", "B": "two words", "C": "x#y", "D": "plain"})   # last duplicate wins

    def test_the_settings_file_is_always_dot_env_in_the_root(self):
        self.assertEqual(envfile.default_path(), ROOT / ".env")

    def test_every_config_key_is_in_dot_env(self):
        have = envfile.parse((ROOT / ".env").read_text(encoding="utf-8"))
        self.assertEqual(sorted(_config_keys() - set(have)), [], ".env lacks keys the code reads")

    def _run(self, env_text, extra_env=None):
        """Run a fresh interpreter whose settings file is a throw-away .env holding only the given text."""
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / ".env").write_text(env_text, encoding="utf-8")
            # config.py loads default_path() at import; point that at the temp file instead of the real .env
            code = ("from pathlib import Path; from nyayavedika import envfile; "
                    f"envfile.default_path = lambda: Path({str(Path(d) / '.env')!r}); "
                    "from nyayavedika import config; print(config.DEMO_MAX_FILES)")
            return subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True,
                                  env={**os.environ, **(extra_env or {})})

    def _full_text(self):
        return (ROOT / ".env").read_text(encoding="utf-8")

    def test_missing_keys_stop_startup_and_are_all_listed(self):
        r = self._run("DEMO_MAX_FILES=5\n")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("missing from the settings file", r.stderr)
        self.assertIn("AZURE_OPENAI_DEPLOYMENT", r.stderr)

    def test_missing_file_is_an_error(self):
        code = ("from pathlib import Path; from nyayavedika import envfile; "
                "envfile.default_path = lambda: Path('/nonexistent/.env'); from nyayavedika import config")
        r = subprocess.run([sys.executable, "-c", code], cwd=ROOT, capture_output=True, text=True)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("Settings file not found", r.stderr)

    def test_shell_environment_is_ignored(self):
        text = re.sub(r"(?m)^DEMO_MAX_FILES=.*$", "DEMO_MAX_FILES=5", self._full_text())
        r = self._run(text, {"DEMO_MAX_FILES": "99"})            # shell value must lose to the file
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(r.stdout.strip(), "5")

    def test_a_redirect_variable_is_not_honoured(self):
        """NYAYAVEDIKA_ENV_FILE used to point the app at another settings file; it must now do nothing."""
        r = subprocess.run([sys.executable, "-c", "from nyayavedika import envfile; print(envfile.default_path())"],
                           cwd=ROOT, capture_output=True, text=True,
                           env={**os.environ, "NYAYAVEDIKA_ENV_FILE": "/somewhere/else.env"})
        self.assertEqual(r.stdout.strip(), str(ROOT / ".env"))

    def test_bad_number_is_reported(self):
        text = re.sub(r"(?m)^DEMO_MAX_FILES=.*$", "DEMO_MAX_FILES=five", self._full_text())
        r = self._run(text)
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("DEMO_MAX_FILES must be a whole number", r.stderr)

    def test_overrides_are_empty_unless_the_test_helper_set_them(self):
        r = subprocess.run([sys.executable, "-c", "from nyayavedika import envfile; print(len(envfile.OVERRIDES))"],
                           cwd=ROOT, capture_output=True, text=True)
        self.assertEqual(r.stdout.strip(), "0")

    def test_no_module_reads_the_environment(self):
        offenders = []
        for p in list((ROOT / "nyayavedika").rglob("*.py")) + [ROOT / "server.py"] + list((ROOT / "scripts").glob("*.py")):
            t = p.read_text(encoding="utf-8", errors="replace")
            if any("os.environ" in l or "getenv(" in l for l in t.splitlines() if not l.lstrip().startswith(("#", '"'))
                   and "Nothing is read from os.environ" not in l and "os.environ is not touched" not in l):
                offenders.append(str(p.relative_to(ROOT)))
        self.assertEqual(offenders, [])

    def test_no_other_settings_file_exists(self):
        skip = {".git", "__pycache__", "node_modules", ".venv", "venv", "storage", "dist"}
        found = []
        for p in ROOT.rglob("*"):
            if p.is_file() and not (set(p.relative_to(ROOT).parts) & skip) and p != ROOT / ".env.example":
                n = p.name.lower()
                if (n == ".env" and p.parent != ROOT) or (n != ".env" and (n.startswith(".env") or n.endswith(".env")
                                                                         or n in ("env.example", ".flaskenv"))):
                    found.append(str(p.relative_to(ROOT)))
        self.assertEqual(found, [], "settings must live in the root .env only")

    def test_no_secret_from_dot_env_is_written_anywhere_else(self):
        have = envfile.parse((ROOT / ".env").read_text(encoding="utf-8"))
        secrets = [v for k, v in have.items() if any(s in k for s in ("API_KEY", "PASSWORD", "TOKEN_", "URL", "URI"))
                   and len(v) >= 12 and "://" not in v[:0] and not v.startswith(("http://", "https://", "sqlite", "change-me"))]
        leaks = []
        for p in ROOT.rglob("*"):
            if not p.is_file() or p == ROOT / ".env" or {".git", "__pycache__", "storage", "dist"} & set(p.relative_to(ROOT).parts):
                continue
            if p.suffix in (".pdf", ".pyc", ".db", ".zip", ".svg"):
                continue
            try:
                t = p.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            if any(s in t for s in secrets):
                leaks.append(str(p.relative_to(ROOT)))
        self.assertEqual(leaks, [])


if __name__ == "__main__":
    unittest.main()
