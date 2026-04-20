"""Instaply doctor — sanity-check the local install.

Runs a series of pass/fail checks and tells you exactly what to fix.
First thing to try when "the agent isn't working" — saves the
maintainer 100+ post-launch issues asking the same handful of things.

Usage:
    python doctor.py
    python doctor.py --json    # machine-readable output for CI / scripts
"""
from __future__ import annotations

import sys as _sys
if _sys.platform == "win32":
    try:
        _sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        _sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, OSError):
        pass

import argparse
import json
import os
import platform
import shutil
import sqlite3
import subprocess
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
CONFIG_DIR = ROOT / "config"
ENV_PATH = CONFIG_DIR / ".env"

# ─────────────────────────────────────────────────────────────────────
#  ANSI helpers
# ─────────────────────────────────────────────────────────────────────
_USE_COLOUR = sys.stdout.isatty() and os.environ.get("NO_COLOR") is None

def _wrap(s: str, code: str) -> str:
    return f"\033[{code}m{s}\033[0m" if _USE_COLOUR else s

def bold(s: str) -> str:    return _wrap(s, "1")
def green(s: str) -> str:   return _wrap(s, "32")
def yellow(s: str) -> str:  return _wrap(s, "33")
def red(s: str) -> str:     return _wrap(s, "31")
def cyan(s: str) -> str:    return _wrap(s, "36")
def dim(s: str) -> str:     return _wrap(s, "2")


# ─────────────────────────────────────────────────────────────────────
#  Check primitives
# ─────────────────────────────────────────────────────────────────────
@dataclass
class Check:
    name: str
    ok: bool
    detail: str = ""
    fix: str = ""

    def render(self) -> str:
        icon = green("✓") if self.ok else red("✗")
        line = f"  {icon} {self.name}"
        if self.detail:
            line += f"  {dim(self.detail)}"
        return line

    def to_dict(self) -> dict:
        return {"name": self.name, "ok": self.ok, "detail": self.detail, "fix": self.fix}


# ─────────────────────────────────────────────────────────────────────
#  Individual checks
# ─────────────────────────────────────────────────────────────────────
def check_python() -> Check:
    v = sys.version_info
    ok = v >= (3, 10)
    return Check(
        name="Python ≥ 3.10",
        ok=ok,
        detail=f"running {v.major}.{v.minor}.{v.micro}",
        fix=("Install Python 3.10+ from https://python.org "
             "(or `brew install python@3.12` on macOS)."),
    )


def _read_env() -> dict[str, str]:
    """Best-effort parser for config/.env without depending on python-dotenv."""
    env = {}
    if not ENV_PATH.exists():
        return env
    for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def check_env_file() -> Check:
    return Check(
        name="config/.env exists",
        ok=ENV_PATH.exists(),
        detail=str(ENV_PATH.relative_to(ROOT)) if ENV_PATH.exists() else "missing",
        fix="Run `python setup.py` to generate it.",
    )


def check_ollama_running(env: dict) -> Check:
    base = env.get("OLLAMA_BASE_URL") or "http://localhost:11434"
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/api/tags", timeout=3) as r:
            ok = r.status == 200
            return Check(
                name=f"Ollama reachable ({base})",
                ok=ok,
                detail=f"HTTP {r.status}",
                fix="Start the daemon: `ollama serve` (or run any `ollama run <model>` once).",
            )
    except (urllib.error.URLError, OSError) as exc:
        return Check(
            name=f"Ollama reachable ({base})",
            ok=False,
            detail=f"unreachable ({exc.__class__.__name__})",
            fix=("If Ollama isn't installed: `python setup.py` will install it. "
                 "If it is installed: start the daemon with `ollama serve`."),
        )


def check_model_pulled(env: dict) -> Check:
    base = env.get("OLLAMA_BASE_URL") or "http://localhost:11434"
    model = env.get("MODEL_NAME") or ""
    if not model:
        return Check(
            name="Configured model pulled",
            ok=False,
            detail="MODEL_NAME not set in .env",
            fix="Re-run `python setup.py` to pick + pull a model.",
        )
    try:
        with urllib.request.urlopen(f"{base.rstrip('/')}/api/tags", timeout=3) as r:
            data = json.loads(r.read().decode("utf-8"))
        names = [m.get("name", "") for m in data.get("models", [])]
        # Match against base name (model can be tagged "qwen3-coder:30b" or "qwen3-coder:latest")
        model_base = model.split(":")[0]
        matches = [n for n in names if n == model or n.startswith(f"{model_base}:")]
        if matches:
            return Check(
                name=f"Model `{model}` pulled",
                ok=True,
                detail=f"available as: {', '.join(matches[:3])}",
            )
        return Check(
            name=f"Model `{model}` pulled",
            ok=False,
            detail=f"not in: {', '.join(names) if names else '(no models)'}",
            fix=f"Run `ollama pull {model}` (size depends on the model — 2-20 GB).",
        )
    except Exception as exc:
        return Check(
            name=f"Model `{model}` pulled",
            ok=False,
            detail=f"can't check ({exc.__class__.__name__})",
            fix="Make sure Ollama is reachable first (the previous check).",
        )


def check_playwright_chromium() -> Check:
    # Playwright stores browsers in ms-playwright/<channel>-XXXXX/<browser>/
    # We just check that `playwright install --dry-run chromium` reports
    # an existing install (its exit code + output reflect missing/present).
    try:
        out = subprocess.check_output(
            [sys.executable, "-m", "playwright", "install", "--dry-run", "chromium"],
            text=True, stderr=subprocess.STDOUT, timeout=10,
        )
        # The dry-run output mentions whether the browser would be installed.
        # If it says "is already installed" (or stays silent w/ no "Install"
        # line), we're good.
        ok = ("already installed" in out.lower()
              or "install location" in out.lower()
              or "is installed" in out.lower())
        return Check(
            name="Playwright Chromium installed",
            ok=ok,
            detail="ready" if ok else "not detected",
            fix="Run `python -m playwright install chromium` (~150 MB, one-time).",
        )
    except subprocess.CalledProcessError as exc:
        return Check(
            name="Playwright Chromium installed",
            ok=False,
            detail=f"playwright CLI errored (exit {exc.returncode})",
            fix="Run `pip install playwright` then `python -m playwright install chromium`.",
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return Check(
            name="Playwright Chromium installed",
            ok=False,
            detail="playwright CLI missing",
            fix="Run `pip install playwright` then `python -m playwright install chromium`.",
        )


def check_profile_json() -> Check:
    path = DATA_DIR / "profile.json"
    if not path.exists():
        return Check(
            name="data/profile.json exists",
            ok=False,
            detail="missing",
            fix="Run `python setup.py profile` to generate it interactively.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check(
            name="data/profile.json valid JSON",
            ok=False,
            detail=str(exc),
            fix="Fix the syntax error or re-run `python setup.py profile --force`.",
        )
    target_roles = (
        data.get("target_roles")
        or (data.get("targets") or {}).get("roles")
        or []
    )
    missing = []
    if not data.get("name"):
        missing.append("name")
    if not (data.get("contact") or {}).get("email"):
        missing.append("contact.email")
    if not target_roles:
        missing.append("targets.roles / target_roles")
    if missing:
        return Check(
            name="data/profile.json complete",
            ok=False,
            detail=f"missing: {', '.join(missing)}",
            fix="Re-run `python setup.py profile` to fill the gaps.",
        )
    return Check(
        name="data/profile.json valid",
        ok=True,
        detail=f"{data['name']} / {len(target_roles)} target roles",
    )
    return Check(
        name="data/profile.json valid",
        ok=True,
        detail=f"{data['name']} · {len((data.get('targets') or {}).get('roles', []))} target roles",
    )


def check_master_resume_json() -> Check:
    path = DATA_DIR / "master-resume.json"
    if not path.exists():
        return Check(
            name="data/master-resume.json exists",
            ok=False,
            detail="missing",
            fix="Run `python setup.py profile` to generate it.",
        )
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        return Check(
            name="data/master-resume.json valid JSON",
            ok=False,
            detail=str(exc),
            fix="Fix the syntax error or re-run `python setup.py profile --force`.",
        )
    if not data.get("name"):
        return Check(
            name="data/master-resume.json complete",
            ok=False,
            detail="missing 'name'",
            fix="Re-run `python setup.py profile` to repopulate.",
        )
    return Check(
        name="data/master-resume.json valid",
        ok=True,
        detail=f"{len(data.get('skills', []))} skills · {len(data.get('education', []))} education entries",
    )


def check_sqlite_writable(env: dict) -> Check:
    db_path = Path(env.get("DATABASE_PATH") or DATA_DIR / "jobs.db")
    if not db_path.is_absolute():
        db_path = ROOT / db_path
    db_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        c = sqlite3.connect(str(db_path))
        c.execute("CREATE TABLE IF NOT EXISTS _doctor_check (x INTEGER)")
        c.execute("DROP TABLE _doctor_check")
        c.close()
        return Check(
            name=f"SQLite writable ({db_path.relative_to(ROOT) if db_path.is_relative_to(ROOT) else db_path})",
            ok=True,
        )
    except (sqlite3.Error, OSError) as exc:
        return Check(
            name=f"SQLite writable ({db_path})",
            ok=False,
            detail=str(exc),
            fix="Check the parent directory exists and is writable.",
        )


def check_data_dir() -> Check:
    return Check(
        name="data/ directory writable",
        ok=os.access(DATA_DIR, os.W_OK) if DATA_DIR.exists() else os.access(ROOT, os.W_OK),
        detail=str(DATA_DIR.relative_to(ROOT)),
        fix="`mkdir agent/data` and ensure it's writable.",
    )


def check_required_modules() -> Check:
    """Make sure the runtime deps the loop needs at boot are importable."""
    missing = []
    for mod in ("playwright", "httpx", "pydantic", "bs4", "lxml"):
        try:
            __import__(mod)
        except ImportError:
            missing.append(mod)
    if missing:
        return Check(
            name="Python dependencies installed",
            ok=False,
            detail=f"missing: {', '.join(missing)}",
            fix=f"Run `pip install {' '.join(missing)}`.",
        )
    return Check(
        name="Python dependencies installed",
        ok=True,
        detail="playwright, httpx, pydantic, bs4, lxml",
    )


# ─────────────────────────────────────────────────────────────────────
#  Main
# ─────────────────────────────────────────────────────────────────────
def main(argv: Optional[list[str]] = None) -> int:
    ap = argparse.ArgumentParser(description="Instaply local-install health check.")
    ap.add_argument("--json", action="store_true", help="Emit machine-readable JSON, exit 0.")
    args = ap.parse_args(argv)

    env = _read_env()
    checks: list[Check] = [
        check_python(),
        check_required_modules(),
        check_env_file(),
        check_ollama_running(env),
        check_model_pulled(env),
        check_playwright_chromium(),
        check_data_dir(),
        check_sqlite_writable(env),
        check_profile_json(),
        check_master_resume_json(),
    ]

    if args.json:
        print(json.dumps({
            "ok": all(c.ok for c in checks),
            "checks": [c.to_dict() for c in checks],
        }, indent=2))
        return 0

    print(bold(cyan("\nInstaply doctor\n")))
    for c in checks:
        print(c.render())

    failed = [c for c in checks if not c.ok]
    print()
    if not failed:
        print(green(bold(f"  All {len(checks)} checks passed. The agent should run.")))
        print(dim(f"  Try: {bold('python run.py')}"))
        return 0

    print(red(bold(f"  {len(failed)} of {len(checks)} checks failed:")))
    for c in failed:
        print(f"    {red('✗')} {bold(c.name)}")
        if c.detail:
            print(f"      {dim(c.detail)}")
        if c.fix:
            print(f"      → {c.fix}")
    print()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
