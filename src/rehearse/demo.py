"""Offline demo. Forces fixture mode even if the demo config is edited."""

from __future__ import annotations

from pathlib import Path

from rehearse.config import Config, load_config
from rehearse.engine import Report, check_paths
from rehearse.locate import demo_root
from rehearse.runbook_load import discover_runbooks


def load_demo_config() -> tuple[Config, list[Path]]:
    root = demo_root()
    config = load_config(root / "rehearse.yaml")
    config.mode = "offline"
    paths = discover_runbooks(root / "runbooks")
    return config, paths


def run_demo() -> Report:
    config, paths = load_demo_config()
    return check_paths(paths, config)
