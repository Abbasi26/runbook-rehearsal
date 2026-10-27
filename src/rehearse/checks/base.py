"""Check plugin interface.

v0.1 ships the built-in checks below. A check reads the runbook and returns
findings. It does not modify the runbook, the referenced hosts, or the scripts.
Third-party entry points are not loaded in this version; add a class to
``default_checks`` in-tree.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from rehearse.models import Runbook


@dataclass
class CheckContext:
    config: object
    clock: object
    network: object
    directory: object
    seen_urls: set[str] = field(default_factory=set)


class Check:
    name = "check"
    dimension = "completeness"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        raise NotImplementedError
