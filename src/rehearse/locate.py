"""Find the schema and the offline demo fixtures."""

from __future__ import annotations

import os
from pathlib import Path


def schema_path() -> Path:
    packaged = Path(__file__).resolve().parent / "data" / "runbook.schema.json"
    if packaged.is_file():
        return packaged
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "schema" / "runbook.schema.json"
        if candidate.is_file():
            return candidate
    raise FileNotFoundError("runbook.schema.json")


def repo_schema_path() -> Path | None:
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "schema" / "runbook.schema.json"
        if candidate.is_file():
            return candidate
    return None


def powershell_helper() -> Path:
    return Path(__file__).resolve().parent / "data" / "Test-ScriptSyntax.ps1"


def demo_root() -> Path:
    env = os.environ.get("REHEARSE_DEMO_ROOT")
    if env:
        path = Path(env).expanduser()
        if (path / "rehearse.yaml").is_file():
            return path
        raise FileNotFoundError(f"REHEARSE_DEMO_ROOT does not contain rehearse.yaml: {path}")
    for parent in Path(__file__).resolve().parents:
        candidate = parent / "examples" / "demo"
        if (candidate / "rehearse.yaml").is_file():
            return candidate
    raise FileNotFoundError(
        "examples/demo was not found. Run from a git checkout or set REHEARSE_DEMO_ROOT."
    )
