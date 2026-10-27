"""Script syntax check. Parse only."""

from __future__ import annotations

from rehearse.checks.base import Check, CheckContext
from rehearse.checks.files import resolve_reference
from rehearse.models import Runbook, iter_assets, make_finding
from rehearse.syntax import check_script


class ScriptCheck(Check):
    name = "script-syntax"
    dimension = "references"

    def run(self, runbook: Runbook, ctx: CheckContext) -> list:
        findings = []
        for _step, asset in iter_assets(runbook, "script"):
            path = resolve_reference(runbook.path, asset.target)
            result = check_script(path, asset.language)
            findings.append(
                make_finding(
                    check=self.name,
                    dimension=self.dimension,
                    status=result.status,
                    runbook_id=runbook.id,
                    target=asset.target,
                    message=result.message,
                    asset=asset.id,
                    language=asset.language,
                    details=result.details,
                )
            )
        return findings
