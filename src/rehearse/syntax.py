"""Parse scripts. Nothing in this module executes the script body."""

from __future__ import annotations

import json
import shutil
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

from rehearse.locate import powershell_helper

EXTENSIONS = {
    ".ps1": "powershell",
    ".sh": "bash",
    ".bash": "bash",
    ".py": "python",
}


@dataclass
class ScriptResult:
    status: str
    message: str
    details: list[str] = field(default_factory=list)


def check_script(path: Path, language: str | None) -> ScriptResult:
    chosen = language or EXTENSIONS.get(path.suffix.lower())
    if chosen is None:
        return ScriptResult("warn", "no syntax checker for this language")
    if not path.is_file():
        return ScriptResult("fail", "script file not found")
    if chosen == "python":
        return _check_python(path)
    if chosen == "bash":
        return _check_bash(path)
    if chosen == "powershell":
        return _check_powershell(path)
    return ScriptResult("warn", f"no syntax checker for language {chosen}")


def _check_python(path: Path) -> ScriptResult:
    try:
        source = path.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return ScriptResult("fail", "script is not UTF-8 text")
    try:
        compile(source, str(path), "exec")
    except SyntaxError as exc:
        line = exc.lineno or 0
        detail = exc.msg or "syntax error"
        return ScriptResult("fail", f"Python syntax error at line {line}: {detail}", [detail])
    return ScriptResult("pass", "Python compile() accepted the file; it was not executed")


def _check_bash(path: Path) -> ScriptResult:
    bash = shutil.which("bash")
    if not bash:
        return ScriptResult("warn", "bash is not on PATH; syntax was not checked")
    try:
        completed = subprocess.run(
            [bash, "-n", str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ScriptResult("fail", "bash -n timed out")
    if completed.returncode == 0:
        return ScriptResult("pass", "bash -n accepted the file; it was not executed")
    detail = (completed.stderr or completed.stdout).strip().replace(str(path), path.name)
    first = detail.splitlines()[0] if detail else f"bash -n exited {completed.returncode}"
    return ScriptResult("fail", f"bash syntax error: {first}", [first])


def _check_powershell(path: Path) -> ScriptResult:
    pwsh = shutil.which("pwsh")
    if not pwsh:
        return ScriptResult(
            "warn",
            "pwsh is not on PATH; PowerShell syntax was not checked "
            "with Parser.ParseFile",
        )
    helper = powershell_helper()
    if not helper.is_file():
        return ScriptResult("fail", "bundled PowerShell parser helper is missing")
    try:
        completed = subprocess.run(
            [pwsh, "-NoProfile", "-NonInteractive", "-File", str(helper), str(path)],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return ScriptResult("fail", "pwsh Parser.ParseFile timed out")
    stdout = (completed.stdout or "").strip()
    if not stdout:
        stderr = (completed.stderr or "").strip().splitlines()
        detail = stderr[0] if stderr else f"pwsh exited {completed.returncode}"
        return ScriptResult("fail", f"PowerShell parser produced no result: {detail}", [detail])
    try:
        payload = json.loads(stdout)
    except json.JSONDecodeError:
        return ScriptResult("fail", "PowerShell parser output was not JSON")
    errors = payload.get("errors") or []
    if payload.get("ok") and not errors:
        return ScriptResult(
            "pass",
            "Parser.ParseFile accepted the file; it was not executed",
        )
    details = [
        f"{item.get('line')}:{item.get('column')}: {item.get('message')}"
        for item in errors
        if isinstance(item, dict)
    ]
    summary = details[0] if details else "PowerShell syntax error"
    return ScriptResult("fail", f"PowerShell syntax error: {summary}", details[:8])
